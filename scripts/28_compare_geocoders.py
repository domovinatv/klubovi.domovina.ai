"""
Cross-match Nominatim vs Google Maps geocoder. Bucket each club by distance:

  exact   <    50 m   — same building / pin
  close   <   250 m   — same block; consistent
  near    <  1 000 m  — same neighbourhood; usually OK
  regional<  10 000 m — same town but different point of interest
  far     >= 10 000 m — different town or one of the geocoders is wrong

Output:
  - console summary (counts per bucket + match-type breakdown)
  - data/verification/geo_compare.json with full per-club details, sorted by
    distance descending so the worst mismatches surface first.

Reads clubs where BOTH lat (Nominatim) AND lat_google are populated. Run after
scripts/27_google_geocode.py.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "data" / "clubs.db"
OUT = ROOT / "data" / "verification" / "geo_compare.json"
OUT.parent.mkdir(parents=True, exist_ok=True)

BUCKETS = [
    ("exact",     50),
    ("close",    250),
    ("near",    1000),
    ("regional", 10000),
    ("far",     float("inf")),
]


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1 = a
    lat2, lng2 = b
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    h = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def bucket_for(distance_m: float) -> str:
    for name, top in BUCKETS:
        if distance_m < top:
            return name
    return "far"


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, canonical_name, city, county, address, "
        "lat, lng, lat_google, lng_google, google_match_type, "
        "google_place_name, google_formatted_address "
        "FROM clubs WHERE lat IS NOT NULL AND lat_google IS NOT NULL"
    ).fetchall()
    total_paired = len(rows)
    only_nominatim = conn.execute(
        "SELECT COUNT(*) FROM clubs WHERE lat IS NOT NULL AND lat_google IS NULL"
    ).fetchone()[0]
    only_google = conn.execute(
        "SELECT COUNT(*) FROM clubs WHERE lat IS NULL AND lat_google IS NOT NULL"
    ).fetchone()[0]
    neither = conn.execute(
        "SELECT COUNT(*) FROM clubs WHERE lat IS NULL AND lat_google IS NULL"
    ).fetchone()[0]

    print(f"paired (both geocoders): {total_paired}")
    print(f"  only Nominatim:        {only_nominatim}")
    print(f"  only Google:           {only_google}")
    print(f"  neither:               {neither}")
    print()

    items = []
    bucket_counts: Counter[str] = Counter()
    match_type_by_bucket: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        d = haversine_m((r["lat"], r["lng"]), (r["lat_google"], r["lng_google"]))
        b = bucket_for(d)
        bucket_counts[b] += 1
        match_type_by_bucket[b][r["google_match_type"] or "?"] += 1
        items.append({
            "id": r["id"],
            "canonical_name": r["canonical_name"],
            "city": r["city"],
            "county": r["county"],
            "address": r["address"],
            "lat_nominatim": r["lat"], "lng_nominatim": r["lng"],
            "lat_google": r["lat_google"], "lng_google": r["lng_google"],
            "google_place_name": r["google_place_name"],
            "google_formatted_address": r["google_formatted_address"],
            "google_match_type": r["google_match_type"],
            "distance_m": round(d, 1),
            "bucket": b,
        })

    items.sort(key=lambda x: -x["distance_m"])

    print("bucket          n     match-type breakdown")
    for name, _ in BUCKETS:
        n = bucket_counts.get(name, 0)
        pct = 100 * n / total_paired if total_paired else 0
        mt = ", ".join(f"{k}={v}" for k, v in match_type_by_bucket[name].most_common())
        print(f"  {name:8} {n:4d} ({pct:5.1f}%)  {mt}")

    print(f"\ntop 20 farthest mismatches:")
    for it in items[:20]:
        d_km = it["distance_m"] / 1000
        print(f"  {d_km:6.1f} km  [{it['google_match_type']:20}] "
              f"{it['canonical_name']:35} | {it['city'] or '-':18} "
              f"| google: {it['google_place_name'] or it['google_formatted_address'] or '?'}")

    OUT.write_text(json.dumps({
        "summary": {
            "paired": total_paired,
            "only_nominatim": only_nominatim,
            "only_google": only_google,
            "neither": neither,
            "buckets": dict(bucket_counts),
            "match_type_by_bucket": {k: dict(v) for k, v in match_type_by_bucket.items()},
        },
        "items": items,
    }, ensure_ascii=False, indent=2))
    print(f"\nfull report: {OUT}")


if __name__ == "__main__":
    main()
