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
    """Call Places API (New) Text Search. Cached."""
    body = {"textQuery": text, "regionCode": "HR", "languageCode": "hr",
            "maxResultCount": 5}
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


def resolve(client: httpx.Client, api_key: str, club: dict) -> dict | None:
    """Resolve one club. Returns dict with lat/lng/place_id/etc, or None."""
    cname = club["canonical_name"]
    city = (club.get("city") or "").strip()
    county = (club.get("county") or "").replace(" županija", "").strip()
    address = (club.get("address") or "").strip()

    # 1. Places Text Search with full context
    q_full = f"{cname}, {city}, Hrvatska" if city else f"{cname}, {county}, Hrvatska" if county else f"{cname}, Hrvatska"
    data = places_text_search(client, api_key, q_full)
    if data and (places := data.get("places")):
        p = pick_best_place(places)
        if p and (loc := p.get("location")):
            return {
                "lat": loc["latitude"],
                "lng": loc["longitude"],
                "place_id": p.get("id"),
                "place_name": (p.get("displayName") or {}).get("text"),
                "formatted_address": p.get("formattedAddress"),
                "match_type": "places_textsearch",
            }

    # 2. Classic Geocoding API on the address
    if address:
        addr_q = f"{address}, Hrvatska" if "hrvatska" not in address.lower() else address
        data = geocoding_address(client, api_key, addr_q)
        results = (data or {}).get("results") or []
        if results:
            r0 = results[0]
            loc = r0["geometry"]["location"]
            return {
                "lat": loc["lat"],
                "lng": loc["lng"],
                "place_id": r0.get("place_id"),
                "place_name": None,
                "formatted_address": r0.get("formatted_address"),
                "match_type": "geocoding_address",
            }

    # 3. Last resort: Places Text Search on bare name
    data = places_text_search(client, api_key, f"{cname} nogometni klub Hrvatska")
    if data and (places := data.get("places")):
        p = pick_best_place(places)
        if p and (loc := p.get("location")):
            return {
                "lat": loc["latitude"],
                "lng": loc["longitude"],
                "place_id": p.get("id"),
                "place_name": (p.get("displayName") or {}).get("text"),
                "formatted_address": p.get("formattedAddress"),
                "match_type": "places_name_only",
            }
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="Process only the first N clubs (for smoke tests).")
    ap.add_argument("--only-missing", action="store_true",
                    help="Skip clubs that already have lat_google set.")
    args = ap.parse_args()

    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        raise SystemExit(f"{API_KEY_ENV} not set. Add to .env or export it.")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    sql = ("SELECT id, canonical_name, city, county, address, lat_google "
           "FROM clubs ORDER BY id")
    rows = [dict(r) for r in conn.execute(sql).fetchall()]
    if args.only_missing:
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
