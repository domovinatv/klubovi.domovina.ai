"""
Independent Google Maps geocoder. Does NOT touch clubs.lat / clubs.lng (those
remain the Nominatim source of truth). Writes a parallel set of columns:

  lat_google, lng_google, google_place_id, google_place_name,
  google_formatted_address, google_match_type

`google_match_type` is one of:
  - "places_textsearch": Places API Text Search returned a POI for
        '{canonical_name}, {city}, Hrvatska'. Best signal — usually a stadium
        / clubhouse pin.
  - "geocoding_address": Geocoding API resolved the literal address. Used
        when Places Text Search returns nothing or no acceptable type.
  - "places_name_only": Places Text Search for just the canonical name (no
        city). Last-resort fallback for clubs whose city field is empty.

Caches every response under data/raw/google_maps/ keyed by SHA of the request,
so reruns and the cross-matcher (scripts/28_compare_geocoders.py) are free.

Cost on Google's free tier:
  - Places Text Search (New): $32/1k reqs, $200/mo free = 6 250 reqs/mo.
  - Geocoding API: $5/1k reqs, $200/mo free = 40 000 reqs/mo.
  - 901 clubs × (1 Places + maybe 1 Geocoding fallback) ≈ $30 worst case → free.

Run:
  export GOOGLE_MAPS_API_KEY=...
  uv run python scripts/27_google_geocode.py [--limit N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

DB = ROOT / "data" / "clubs.db"
CACHE_DIR = ROOT / "data" / "raw" / "google_maps"

API_KEY_ENV = "GOOGLE_MAPS_API_KEY"
PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# Field mask = only what we need; reduces SKU cost for Places (New).
# id + displayName + formattedAddress + location is the "Essentials" tier.
PLACES_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.location,places.types,places.primaryType"
)

# Accept only POIs that look like a real club venue. Anything more generic
# (route, locality, neighborhood) will fall through to the Geocoding API
# branch where address-based lookup is the better signal.
GOOD_PLACE_TYPES = {
    "stadium", "sports_complex", "establishment", "point_of_interest",
    "soccer_field", "athletic_field", "amusement_park",  # OSM-style fallbacks
}
BAD_PLACE_TYPES = {"locality", "political", "country", "administrative_area"}

# Croatia bbox — used to drop cross-border hits (Slovenia, BiH, Serbia).
# Generous on the edges so islands and inland borders are inside.
HR_LAT = (42.30, 46.60)
HR_LNG = (13.40, 19.50)

# Strip these from canonical_name so Google receives a clean query. The
# parenthetical disambiguators ((S), (G), (NP), ...) and short tags ("MM")
# confuse Places' relevance ranking and silently match the first generic
# "NK Sloboda" pin regardless of which one we asked for.
_PAREN = re.compile(r"\s*\([^)]+\)\s*$")
_QUOTES = re.compile(r"[\"„""'`]")
_PREFIX_TOKEN = re.compile(
    r"^(HNK|GNK|NK|RNK|MNK|HAŠK|HRNK|ŠNK|GŠNK|BŠK|ŠNM|HNŠK)\b",
    re.IGNORECASE,
)


def clean_name(canonical: str) -> str:
    n = _QUOTES.sub(" ", canonical or "")
    n = _PAREN.sub("", n).strip()
    n = re.sub(r"\s+", " ", n).strip()
    return n


def in_hr(lat: float, lng: float) -> bool:
    return HR_LAT[0] <= lat <= HR_LAT[1] and HR_LNG[0] <= lng <= HR_LNG[1]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("google_geo")


def cache_path(kind: str, payload: dict | str) -> Path:
    body = json.dumps(payload, sort_keys=True) if isinstance(payload, dict) else payload
    h = hashlib.sha256(f"{kind}|{body}".encode()).hexdigest()[:16]
    return CACHE_DIR / kind / f"{h}.json"


def _cached(kind: str, payload: dict | str) -> dict | None:
    cp = cache_path(kind, payload)
    if cp.exists():
        return json.loads(cp.read_text())
    return None


def _store(kind: str, payload: dict | str, response: dict) -> None:
    cp = cache_path(kind, payload)
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(response, ensure_ascii=False, indent=2))


def places_text_search(client: httpx.Client, api_key: str, text: str) -> dict | None:
    """Call Places API (New) Text Search. Cached.

    Includes a `locationRestriction` rectangle around Croatia: `regionCode`
    alone is only a soft bias and lets cross-border hits leak in (NK Olimpija
    matched Ljubljana, Slovenia in the first run). The hard bbox forces
    Google to drop anything outside HR.
    """
    body = {
        "textQuery": text, "regionCode": "HR", "languageCode": "hr",
        "maxResultCount": 5,
        "locationRestriction": {
            "rectangle": {
                "low": {"latitude": HR_LAT[0], "longitude": HR_LNG[0]},
                "high": {"latitude": HR_LAT[1], "longitude": HR_LNG[1]},
            }
        },
    }
    if (hit := _cached("places", body)) is not None:
        return hit
    r = client.post(
        PLACES_URL,
        json=body,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": PLACES_FIELD_MASK,
        },
        timeout=20,
    )
    if r.status_code != 200:
        log.warning("places %d for %r: %s", r.status_code, text, r.text[:200])
        return None
    data = r.json()
    _store("places", body, data)
    return data


def geocoding_address(client: httpx.Client, api_key: str, address: str) -> dict | None:
    """Call classic Geocoding API. Cached."""
    params = {"address": address, "region": "hr", "language": "hr", "key": api_key}
    # Don't cache the API key in the path
    cache_key = {"address": address}
    if (hit := _cached("geocode", cache_key)) is not None:
        return hit
    r = client.get(GEOCODE_URL, params=params, timeout=20)
    if r.status_code != 200:
        log.warning("geocode %d for %r", r.status_code, address)
        return None
    data = r.json()
    _store("geocode", cache_key, data)
    return data


def pick_best_place(places: list[dict]) -> dict | None:
    """First place whose type set is acceptable. Falls back to the first place
    overall if nothing scores cleanly — Google's relevance order is usually
    right for HR football queries."""
    if not places:
        return None
    for p in places:
        types = set(p.get("types") or [])
        if BAD_PLACE_TYPES & types:
            continue
        if GOOD_PLACE_TYPES & types or "sport" in str(p.get("primaryType", "")):
            return p
    return places[0]


_NON_HR_COUNTRIES = (
    "slovenija", "slovenia", "bosna i hercegovina", "bosnia", "bih",
    "srbija", "serbia", "crna gora", "montenegro", "italija", "italy",
    "mađarska", "magyarország", "hungary",
)


def _take_place(p: dict, match_type: str) -> dict | None:
    """Extract a Place dict if its location is inside HR; otherwise None.

    `locationRestriction` in Places searchText is advisory — establishments
    near the border still leak through (NK Olimpija Ljubljana matched even
    with the HR rectangle set). The reliable filter is `formattedAddress`:
    Google with `languageCode: hr` returns the country in Croatian, and
    foreign addresses end with the foreign country name.
    """
    loc = p.get("location") or {}
    if "latitude" not in loc or "longitude" not in loc:
        return None
    lat, lng = float(loc["latitude"]), float(loc["longitude"])
    if not in_hr(lat, lng):
        return None
    addr_low = (p.get("formattedAddress") or "").lower()
    if any(c in addr_low for c in _NON_HR_COUNTRIES):
        return None
    return {
        "lat": lat, "lng": lng,
        "place_id": p.get("id"),
        "place_name": (p.get("displayName") or {}).get("text"),
        "formatted_address": p.get("formattedAddress"),
        "match_type": match_type,
    }


def resolve(client: httpx.Client, api_key: str, club: dict) -> dict | None:
    """Resolve one club. Tries several query shapes from most-disambiguated
    to bare; returns the first whose Place sits inside the HR bbox."""
    cname = clean_name(club["canonical_name"])
    city = (club.get("city") or "").strip()
    county = (club.get("county") or "").replace(" županija", "").strip()
    address = (club.get("address") or "").strip()

    # Queries from most specific to most general. We always include county
    # when known — without it, generic names like "NK Sloboda" all match the
    # same first pin, regardless of which Sloboda we asked for.
    queries = []
    if city and county:
        queries.append(f"{cname}, {city}, {county}, Hrvatska")
    if city:
        queries.append(f"{cname}, {city}, Hrvatska")
    if county:
        queries.append(f"{cname}, {county}, Hrvatska")
    queries.append(f"{cname}, Hrvatska")
    # Dedupe preserving order.
    seen: set[str] = set()
    queries = [q for q in queries if not (q in seen or seen.add(q))]

    for q in queries:
        data = places_text_search(client, api_key, q)
        for p in (data or {}).get("places") or []:
            res = _take_place(p, "places_textsearch")
            if res:
                return res

    # Geocoding API on the literal address (when Places had no acceptable hit).
    if address:
        addr_q = f"{address}, Hrvatska" if "hrvatska" not in address.lower() else address
        data = geocoding_address(client, api_key, addr_q)
        for r0 in (data or {}).get("results") or []:
            loc = r0["geometry"]["location"]
            if not in_hr(loc["lat"], loc["lng"]):
                continue
            return {
                "lat": loc["lat"], "lng": loc["lng"],
                "place_id": r0.get("place_id"),
                "place_name": None,
                "formatted_address": r0.get("formatted_address"),
                "match_type": "geocoding_address",
            }

    # Last resort: Places search on bare name + "nogometni klub" hint.
    data = places_text_search(client, api_key, f"{cname} nogometni klub Hrvatska")
    for p in (data or {}).get("places") or []:
        res = _take_place(p, "places_name_only")
        if res:
            return res
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="Process only the first N clubs (for smoke tests).")
    ap.add_argument("--only-missing", action="store_true",
                    help="Skip clubs that already have lat_google set.")
    ap.add_argument("--reprocess-far", action="store_true",
                    help="Clear and re-resolve clubs in the 'regional' and "
                         "'far' buckets (Nominatim/Google distance >= 1km).")
    args = ap.parse_args()

    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        raise SystemExit(f"{API_KEY_ENV} not set. Add to .env or export it.")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    sql = ("SELECT id, canonical_name, city, county, address, lat, lng, lat_google, lng_google "
           "FROM clubs ORDER BY id")
    rows = [dict(r) for r in conn.execute(sql).fetchall()]
    if args.reprocess_far:
        import math
        def d_km(a, b, c, dd):
            if None in (a, b, c, dd):
                return 0
            R = 6371.0
            p1, p2 = math.radians(a), math.radians(c)
            dlat = math.radians(c - a); dlng = math.radians(dd - b)
            h = math.sin(dlat/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlng/2)**2
            return 2*R*math.asin(math.sqrt(h))
        before = len(rows)
        rows = [r for r in rows
                if d_km(r["lat"], r["lng"], r["lat_google"], r["lng_google"]) >= 1.0
                or r["lat_google"] is None]
        log.info("reprocess-far: %d clubs (out of %d) need re-resolve", len(rows), before)
        # Clear lat_google so a cache miss / different query path is used.
        # We do not delete the cache files — new query strings will land in
        # fresh cache entries automatically.
        for r in rows:
            conn.execute(
                "UPDATE clubs SET lat_google=NULL, lng_google=NULL, "
                "google_place_id=NULL, google_place_name=NULL, "
                "google_formatted_address=NULL, google_match_type=NULL "
                "WHERE id=?", (r["id"],),
            )
        conn.commit()
    elif args.only_missing:
        rows = [r for r in rows if r.get("lat_google") is None]
    if args.limit:
        rows = rows[: args.limit]
    log.info("clubs to geocode via Google: %d", len(rows))

    counters = {"places_textsearch": 0, "geocoding_address": 0,
                "places_name_only": 0, "no_hit": 0}
    with httpx.Client() as hx:
        for i, club in enumerate(rows, 1):
            res = resolve(hx, api_key, club)
            if not res:
                counters["no_hit"] += 1
                log.info("[%d/%d] %s: no hit", i, len(rows), club["canonical_name"])
                continue
            counters[res["match_type"]] += 1
            conn.execute(
                "UPDATE clubs SET lat_google=?, lng_google=?, google_place_id=?, "
                "google_place_name=?, google_formatted_address=?, google_match_type=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (res["lat"], res["lng"], res["place_id"], res["place_name"],
                 res["formatted_address"], res["match_type"], club["id"]),
            )
            if i % 25 == 0:
                conn.commit()
                log.info("[%d/%d] last=%s match=%s",
                         i, len(rows), club["canonical_name"], res["match_type"])
        conn.commit()
    log.info("done. counters=%s", counters)


if __name__ == "__main__":
    main()
