"""READ-ONLY: list clubs whose geo verification was confirmed against a city
that the backfill itself invented.

`scripts/27_google_geocode.py` builds its query from `{canonical_name}, {city},
Hrvatska`. When `city` arrived via a namesake-leaked Firecrawl extraction, the
query asks Google about the WRONG place, Google answers about the wrong club,
and Nominatim — geocoding the same poisoned address — agrees. The pair then
records `geo_source='both'`, which reads as "two independent sources confirm
this marker" but is really one bad source counted twice.

Club 888 (NK Mladost (Z), actually Zabok) is the worked example: backfill wrote
`city='Bjelovar'`, the geocoders both found NK Mladost Ždralovi, and the row
ended up flagged `geo_source='both'`, `geo_truth_source='osm:tie'`.

So: `geo_source='both'` is NOT evidence of correctness when `city` came from
backfill. This script exports those rows for re-verification. It changes
nothing — re-geocoding happens only after the city is repaired.

Run:
  uv run python scripts/62_reverify_geo.py
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.collisions import PAREN_RE  # noqa: E402
from src.db import DB_PATH, connect  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("reverify_geo")

OUT_CSV = ROOT / "data" / "exports" / "geo_suspect.csv"
COLLISIONS_CSV = ROOT / "data" / "exports" / "collisions.csv"

HEADER = [
    "club_id", "slug", "canonical_name", "city", "county", "paren_name",
    "geo_source", "geo_truth_source", "lat", "lng",
    "backfill_runs_with_city", "backfill_source_urls", "collision_orphan_fields",
]


def clubs_with_backfilled_city(conn) -> dict[int, list[dict]]:
    """club_id -> the backfill runs that wrote `city`.

    `fields_filled` is a JSON array; a LIKE on the raw text would also match a
    run that wrote, say, `city_code`, so parse it properly.
    """
    hits: dict[int, list[dict]] = defaultdict(list)
    rows = conn.execute(
        "SELECT run_id, club_id, ran_at, fields_filled, source_urls "
        "FROM backfill_runs WHERE fields_filled LIKE '%city%' ORDER BY run_id"
    ).fetchall()
    for row in rows:
        try:
            fields = json.loads(row["fields_filled"] or "[]")
        except json.JSONDecodeError:
            continue
        if "city" in fields:
            hits[row["club_id"]].append(dict(row))
    return hits


def orphan_fields_by_club(path: Path) -> dict[int, set[str]]:
    """Cross-reference scripts/60 output when it exists — a club that is both
    geo-suspect and an identity orphan is the highest-confidence bad row."""
    if not path.exists():
        return {}
    out: dict[int, set[str]] = defaultdict(set)
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["verdict"] == "orphan":
                out[int(row["club_id"])].add(row["field"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--out-csv", type=Path, default=OUT_CSV)
    ap.add_argument("--collisions-csv", type=Path, default=COLLISIONS_CSV)
    ap.add_argument("--all-geo-sources", action="store_true",
                    help="Include clubs regardless of geo_source, not just "
                         "the falsely-confirmed geo_source='both' rows.")
    args = ap.parse_args()

    conn = connect(args.db)
    backfilled = clubs_with_backfilled_city(conn)
    orphans = orphan_fields_by_club(args.collisions_csv)
    log.info("clubs whose city was written by backfill: %d", len(backfilled))

    clubs = {
        r["id"]: dict(r)
        for r in conn.execute(
            "SELECT id, slug, canonical_name, city, county, geo_source, "
            "geo_truth_source, lat, lng FROM clubs ORDER BY id"
        )
    }
    conn.close()

    suspect = []
    for club_id, runs in backfilled.items():
        club = clubs.get(club_id)
        if club is None:
            continue
        if not args.all_geo_sources and club["geo_source"] != "both":
            continue
        suspect.append((club, runs))

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        for club, runs in sorted(suspect, key=lambda t: t[0]["id"]):
            urls = []
            for r in runs:
                try:
                    urls.extend(json.loads(r["source_urls"] or "[]"))
                except json.JSONDecodeError:
                    pass
            writer.writerow([
                club["id"], club["slug"], club["canonical_name"],
                club["city"] or "", club["county"] or "",
                int(bool(PAREN_RE.search(club["canonical_name"] or ""))),
                club["geo_source"] or "", club["geo_truth_source"] or "",
                club["lat"], club["lng"],
                len(runs), " | ".join(dict.fromkeys(urls)),
                ",".join(sorted(orphans.get(club["id"], ()))),
            ])

    paren = sum(1 for c, _ in suspect if PAREN_RE.search(c["canonical_name"] or ""))
    also_orphan = sum(1 for c, _ in suspect if c["id"] in orphans)
    log.info("wrote %s", args.out_csv)
    print()
    print(f"{'falsely-confirmed geo rows':<34} {len(suspect):>5}")
    print(f"{'  of which paren-disambiguated':<34} {paren:>5}")
    print(f"{'  of which also identity orphans':<34} {also_orphan:>5}")


if __name__ == "__main__":
    main()
