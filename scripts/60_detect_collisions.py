"""READ-ONLY diagnostic: find clubs that share an identity value.

A namesake leak shows up as two or more clubs holding the same phone, email,
website, OIB or coordinate — only one of them can actually own it. This script
groups every identity field, scores an owner candidate per group with the
deterministic signals in `src/collisions.py`, and writes the verdicts out for
review.

It never writes to clubs.db. `scripts/61_quarantine_leaks.py` consumes the CSV
this produces and is the only script allowed to repair anything.

Run:
  uv run python scripts/60_detect_collisions.py
  uv run python scripts/60_detect_collisions.py --field phone --field email
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.collisions import FIELD_SPECS, build_groups, resolve_group  # noqa: E402
from src.db import DB_PATH, connect  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("detect_collisions")

OUT_CSV = ROOT / "data" / "exports" / "collisions.csv"
OUT_JSON = ROOT / "data" / "exports" / "collisions_summary.json"

# Every column the scoring signals read. Kept explicit so a schema change
# surfaces here rather than as a silently-missing signal.
CLUB_COLUMNS = (
    "id", "slug", "canonical_name", "city", "county",
    "phone", "phone_e164", "email", "website", "fb_url", "ig_url",
    "oib", "address", "lat", "lng",
    "registry_naziv", "semafor_url", "sofascore_url",
)

CSV_HEADER = [
    "group_key", "field", "value", "club_id", "slug", "canonical_name",
    "city", "county", "owner_score", "owner_reason", "verdict",
]


def load_clubs(conn) -> list[dict]:
    cols = ", ".join(CLUB_COLUMNS)
    return [dict(r) for r in conn.execute(f"SELECT {cols} FROM clubs ORDER BY id")]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--field", action="append", dest="fields", default=None,
                    help="Restrict to these identity fields (repeatable). "
                         f"Choices: {', '.join(s.name for s in FIELD_SPECS)}")
    ap.add_argument("--out-csv", type=Path, default=OUT_CSV)
    ap.add_argument("--out-json", type=Path, default=OUT_JSON)
    args = ap.parse_args()

    specs = FIELD_SPECS
    if args.fields:
        unknown = set(args.fields) - {s.name for s in FIELD_SPECS}
        if unknown:
            raise SystemExit(f"unknown field(s): {sorted(unknown)}")
        specs = tuple(s for s in FIELD_SPECS if s.name in set(args.fields))

    conn = connect(args.db)
    clubs = load_clubs(conn)
    conn.close()
    log.info("loaded %d clubs from %s", len(clubs), args.db)

    groups = build_groups(clubs, specs)
    log.info("collision groups: %d", len(groups))

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    per_field: dict[str, Counter] = defaultdict(Counter)
    affected_clubs: dict[str, set[int]] = defaultdict(set)
    rows_written = 0

    with args.out_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_HEADER)
        for group in groups:
            verdicts = resolve_group(group)
            group_key = f"{group.field}:{group.key}"
            for member in sorted(group.members, key=lambda m: -m.score):
                verdict = verdicts[member.club["id"]]
                per_field[group.field][verdict] += 1
                if verdict == "orphan":
                    affected_clubs[group.field].add(member.club["id"])
                writer.writerow([
                    group_key,
                    group.field,
                    group.key,
                    member.club["id"],
                    member.club["slug"],
                    member.club["canonical_name"],
                    member.club.get("city") or "",
                    member.club.get("county") or "",
                    member.score,
                    " ".join(member.reasons),
                    verdict,
                ])
                rows_written += 1

    summary = {
        "db": str(args.db),
        "clubs_total": len(clubs),
        "groups_total": len(groups),
        "rows": rows_written,
        "by_field": {
            fname: {
                "groups": sum(1 for g in groups if g.field == fname),
                "owner": per_field[fname]["owner"],
                "orphan": per_field[fname]["orphan"],
                "ambiguous": per_field[fname]["ambiguous"],
                "clubs_losing_value": len(affected_clubs[fname]),
            }
            for fname in (s.name for s in specs)
        },
        "clubs_with_any_orphan": len(set().union(*affected_clubs.values()) if affected_clubs else set()),
    }
    args.out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    log.info("wrote %s (%d rows) and %s", args.out_csv, rows_written, args.out_json)
    print()
    print(f"{'field':<12} {'groups':>7} {'owner':>7} {'orphan':>7} {'ambig':>7} {'clubs↓':>7}")
    print("-" * 58)
    for fname, s in summary["by_field"].items():
        print(f"{fname:<12} {s['groups']:>7} {s['owner']:>7} {s['orphan']:>7} "
              f"{s['ambiguous']:>7} {s['clubs_losing_value']:>7}")
    print("-" * 58)
    print(f"clubs with >=1 orphan verdict: {summary['clubs_with_any_orphan']}")


if __name__ == "__main__":
    main()
