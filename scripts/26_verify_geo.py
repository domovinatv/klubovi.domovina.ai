"""
Verify clubs.lat / clubs.lng deterministically. Three independent checks:

  1. Hrvatska bbox: lat 42.3-46.6, lng 13.4-19.5. Catches swaps + out-of-country.
  2. Place-from-name probe: geocode the last token(s) of canonical_name with
     county and compare to current point. > 25km divergence flags an upstream
     city/address mismatch (the ŠNM Naftaš Ivanić → Velika Gorica failure mode).
  3. City probe: geocode "{city}, {county}, Hrvatska" and compare. > 25km flags
     a mismatch between clubs.city and the address that produced lat/lng.

Each check is independent; a row may fail one or more. Output goes to
data/verification/geo_flagged.json and a console summary.

This script makes Nominatim calls only for queries that aren't already cached
in data/raw/nominatim/. With the existing cache from scripts/10, a full run is
~free for clubs whose city/name queries were tried during initial geocoding.

Reverse-geocoding (Nominatim /reverse for admin1) is intentionally NOT added:
it would double the API surface for a check that the place-from-name probe
already covers. Add it later if these three layers miss something.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sqlite3
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "data" / "clubs.db"
CACHE_DIR = ROOT / "data" / "raw" / "nominatim"
OUT = ROOT / "data" / "verification" / "geo_flagged.json"
OUT.parent.mkdir(parents=True, exist_ok=True)

import os
_BASE = os.environ.get("NOMINATIM_ENDPOINT", "https://nominatim.openstreetmap.org").rstrip("/")
ENDPOINT = f"{_BASE}/search"
_LOCAL = any(h in _BASE for h in ("localhost", "127.0.0.1", "nominatim:"))
_THROTTLE = 0.0 if _LOCAL else 1.05
USER_AGENT = "hrnk-baza/0.1 (geo verification pass)"

# Generous Croatia bbox — covers all 901 islands + Istra + Slavonia.
HR_LAT = (42.30, 46.60)
HR_LNG = (13.40, 19.50)

# Distance threshold for "the geocoder for this name/city doesn't agree with
# the stored coords". 25km is wide enough to absorb small-village resolution
# noise while still catching Naftaš-Ivanić-via-Velika-Gorica style errors.
MISMATCH_KM = 25.0

# Strip these prefix tokens from canonical_name when extracting the place token.
_PREFIX = re.compile(
    r"^(HNK|GNK|NK|RNK|MNK|HAŠK|HRNK|ŠNK|GŠNK|BŠK|ŠNM|HNŠK)\s+",
    re.IGNORECASE,
)
_PAREN = re.compile(r"\s*\([^)]+\)\s*$")
_QUOTES = re.compile(r"[\"„""'`]")

log = logging.getLogger("verify_geo")


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1 = a
    lat2, lng2 = b
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    h = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def cache_path(query: str) -> Path:
    h = hashlib.sha256(query.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{h}.json"


def geocode(client: httpx.Client, query: str) -> tuple[float, float] | None:
    cp = cache_path(query)
    if cp.exists():
        data = json.loads(cp.read_text())
    else:
        if _THROTTLE:
            time.sleep(_THROTTLE)
        try:
            r = client.get(
                ENDPOINT,
                params={"q": query, "format": "json", "countrycodes": "hr", "limit": 1},
                headers={"User-Agent": USER_AGENT},
                timeout=15,
            )
        except httpx.HTTPError as e:
            log.warning("network err %r: %s", query, e)
            return None
        if r.status_code != 200:
            log.warning("nominatim %d for %r", r.status_code, query)
            return None
        data = r.json()
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(data, ensure_ascii=False))
    if not data:
        return None
    first = data[0]
    try:
        return float(first["lat"]), float(first["lon"])
    except (KeyError, TypeError, ValueError):
        return None


def name_places(canonical: str) -> list[str]:
    """Plausible place tokens from a club's canonical name.

    "NK Slavonija Ivanovac" -> ["Slavonija Ivanovac", "Ivanovac", "Slavonija"]
    "ŠNM NK\"Naftaš Ivanić\"" -> ["Naftaš Ivanić", "Ivanić", "Naftaš"]
    The single-last-word probe is the most reliable for amateur clubs whose
    name is "{nickname} {village}".
    """
    n = _QUOTES.sub(" ", canonical or "")
    n = _PREFIX.sub("", n).strip()
    n = _PAREN.sub("", n).strip()
    # Drop a leading second prefix token (e.g. ŠNM left "NK Naftaš Ivanić").
    n = _PREFIX.sub("", n).strip()
    if not n:
        return []
    words = [w for w in n.split() if len(w) >= 3]
    if not words:
        return []
    out = [n]
    if len(words) >= 2:
        out.append(words[-1])
        out.append(words[0])
    seen, dedup = set(), []
    for q in out:
        if q in seen:
            continue
        seen.add(q)
        dedup.append(q)
    return dedup


def main():
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT id, canonical_name, city, county, address, lat, lng "
        "FROM clubs WHERE lat IS NOT NULL AND lng IS NOT NULL"
    ).fetchall()
    print(f"checking {len(rows)} geocoded clubs")

    flagged = []
    counters = {"bbox": 0, "name_mismatch": 0, "city_mismatch": 0, "any": 0}

    with httpx.Client(timeout=20) as hx:
        for i, (cid, cname, city, county, addr, lat, lng) in enumerate(rows, 1):
            issues = []

            # 1. bbox
            if not (HR_LAT[0] <= lat <= HR_LAT[1] and HR_LNG[0] <= lng <= HR_LNG[1]):
                issues.append({"check": "bbox", "detail": f"({lat:.4f},{lng:.4f}) out of HR bbox"})
                counters["bbox"] += 1

            point = (lat, lng)
            cnty = (county or "").replace(" županija", "").strip()

            # 2. name probe (smallest place token first)
            name_qs = name_places(cname)
            name_hit = None
            name_q_used = None
            # Try single-word first (most precise for amateur clubs).
            for q in reversed(name_qs):
                full = f"{q}, {cnty}, Hrvatska" if cnty else f"{q}, Hrvatska"
                hit = geocode(hx, full)
                if hit:
                    name_hit = hit
                    name_q_used = full
                    break
            if name_hit:
                d = haversine_km(point, name_hit)
                if d > MISMATCH_KM:
                    issues.append({
                        "check": "name_mismatch",
                        "detail": f"{d:.1f}km from name probe '{name_q_used}' "
                                  f"→ ({name_hit[0]:.4f},{name_hit[1]:.4f})",
                    })
                    counters["name_mismatch"] += 1

            # 3. city probe
            if city:
                city_q = f"{city}, {cnty}, Hrvatska" if cnty else f"{city}, Hrvatska"
                chit = geocode(hx, city_q)
                if chit:
                    d = haversine_km(point, chit)
                    if d > MISMATCH_KM:
                        issues.append({
                            "check": "city_mismatch",
                            "detail": f"{d:.1f}km from '{city_q}' "
                                      f"→ ({chit[0]:.4f},{chit[1]:.4f})",
                        })
                        counters["city_mismatch"] += 1

            if issues:
                counters["any"] += 1
                flagged.append({
                    "id": cid,
                    "canonical_name": cname,
                    "city": city,
                    "county": county,
                    "address": addr,
                    "lat": lat,
                    "lng": lng,
                    "issues": issues,
                })

            if i % 100 == 0:
                print(f"  {i}/{len(rows)}  flagged so far: {counters['any']}")

    flagged.sort(key=lambda f: (-len(f["issues"]), f["canonical_name"]))
    OUT.write_text(json.dumps({"counters": counters, "flagged": flagged},
                              ensure_ascii=False, indent=2))
    print(f"\nfinal counters: {counters}")
    print(f"top 20 flagged:")
    for f in flagged[:20]:
        kinds = ",".join(i["check"] for i in f["issues"])
        print(f"  [{kinds}] {f['canonical_name']:35} | {f['city'] or '-':16} | "
              f"({f['lat']:.4f},{f['lng']:.4f})")
    print(f"\nfull report: {OUT}")


if __name__ == "__main__":
    main()
