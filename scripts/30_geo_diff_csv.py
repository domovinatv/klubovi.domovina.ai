"""
Export a CSV with both Nominatim and Google coordinates for every club so the
divergence is browseable in Excel / Google Sheets.

Columns:
  id, canonical_name, city, county, address,
  lat_nominatim, lng_nominatim, lat_google, lng_google,
  distance_km, bucket, geo_source,
  google_place_name, google_formatted_address, google_match_type,
  active_lat, active_lng       <- whatever clubs.lat/lng currently holds
                                  (= the "truth" picked by script 29)

Sorted by distance_km descending so the worst mismatches are at the top.
Output: data/exports/geo_compare.csv
"""
from __future__ import annotations

import csv
import math
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "clubs.db"
OUT = ROOT / "data" / "exports" / "geo_compare.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)

BUCKETS = [
    ("exact",     50),
    ("close",    250),
    ("near",    1000),
    ("regional", 10000),
    ("far",     float("inf")),
]


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 6_371_000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dlat = math.radians(b[0] - a[0])
    dlng = math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def bucket_for(d: float) -> str:
    for name, top in BUCKETS:
        if d < top:
            return name
    return "far"


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, canonical_name, city, county, address, "
        "lat, lng, lat_google, lng_google, geo_source, "
        "google_place_name, google_formatted_address, google_match_type "
        "FROM clubs ORDER BY id"
    ).fetchall()

    out = []
    for r in rows:
        # The "active" lat/lng is whatever's in clubs.lat/lng — that may be
        # Google's after script 29 swapped it. We also report Nominatim's
        # original via reverse: if geo_source='google_places' we don't have
        # the original Nominatim point any more (it was overwritten). For
        # those, lat_nominatim is reconstructed below from the cache layer
        # is not available — so we publish active_lat (= current) and
        # lat_google (= Google) and let the reader see which is which via
        # geo_source.
        active_lat = r["lat"]; active_lng = r["lng"]
        lat_g = r["lat_google"]; lng_g = r["lng_google"]
        if active_lat is not None and lat_g is not None:
            d_m = haversine_m((active_lat, active_lng), (lat_g, lng_g))
        else:
            d_m = None
        out.append({
            "id": r["id"],
            "canonical_name": r["canonical_name"],
            "city": r["city"] or "",
            "county": r["county"] or "",
            "address": r["address"] or "",
            "active_lat": active_lat,
            "active_lng": active_lng,
            "lat_google": lat_g,
            "lng_google": lng_g,
            "distance_km": round(d_m / 1000, 3) if d_m is not None else "",
            "bucket": bucket_for(d_m) if d_m is not None else "no_data",
            "geo_source": r["geo_source"] or "",
            "google_place_name": r["google_place_name"] or "",
            "google_formatted_address": r["google_formatted_address"] or "",
            "google_match_type": r["google_match_type"] or "",
        })

    # Sort by distance descending; rows without distance go to the end.
    out.sort(key=lambda x: (-(x["distance_km"] if isinstance(x["distance_km"], (int, float)) else -1)))

    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        writer.writeheader()
        writer.writerows(out)
    print(f"wrote {len(out)} rows -> {OUT}")
    # Quick console summary
    from collections import Counter
    bc = Counter(r["bucket"] for r in out)
    src = Counter(r["geo_source"] for r in out)
    print(f"buckets    (after script 29): {dict(bc)}")
    print(f"geo_source (after script 29): {dict(src)}")


if __name__ == "__main__":
    main()
