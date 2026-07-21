"""Quarantine leaked identity values flagged by scripts/60_detect_collisions.py.

Consumes `data/exports/collisions.csv` and, for every `verdict=orphan` row,
NULLs the field that club could not have owned. It never guesses a replacement
— a club with no phone is a club we can re-backfill, a club with the wrong
phone is an SMS sent to a stranger.

  verdict=owner      untouched
  verdict=orphan     field NULLed, logged to `data_repairs`, club queued for
                     re-backfill in `backfill_queue`
  verdict=ambiguous  untouched, exported to collisions_review.csv for a human

Two classes are deliberately NOT repaired here:

  * `latlng` — two clubs on one coordinate is often a genuinely shared pitch,
    and a nulled marker leaves a visible hole in the PWA map. Detect-only;
    see `scripts/62_reverify_geo.py`. `--include-geo` opts in.
  * anything already NULL — that is what makes a second run a no-op.

An orphaned `oib` drags its whole Registar udruga bundle with it: the OIB,
president and registry links all came from the same wrong N:1 match in
`scripts/21_match_udruga.py`, so leaving the president behind would keep
showing another club's chairman on the club page.

DRY RUN BY DEFAULT. Nothing is written without --execute.

Run:
  uv run python scripts/61_quarantine_leaks.py                 # preview
  uv run python scripts/61_quarantine_leaks.py --execute       # repair
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.collisions import FIELDS_BY_NAME, GEO_BUNDLE, REGISTRY_BUNDLE  # noqa: E402
from src.db import DB_PATH, connect  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("quarantine")

IN_CSV = ROOT / "data" / "exports" / "collisions.csv"
REVIEW_CSV = ROOT / "data" / "exports" / "collisions_review.csv"
BACKUP_DIR = ROOT / "data" / "backups"

# Geo is opt-in; everything else in FIELD_SPECS is repaired by default.
GEO_FIELDS = {"latlng"}

REPAIR_SCHEMA = """
CREATE TABLE IF NOT EXISTS data_repairs (
  id         INTEGER PRIMARY KEY,
  club_id    INTEGER NOT NULL REFERENCES clubs(id) ON DELETE CASCADE,
  field      TEXT NOT NULL,
  old_value  TEXT,
  new_value  TEXT,
  reason     TEXT,
  ran_at     TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS backfill_queue (
  club_id    INTEGER PRIMARY KEY REFERENCES clubs(id) ON DELETE CASCADE,
  fields     TEXT,      -- JSON array of columns awaiting a fresh backfill
  reason     TEXT,
  queued_at  TEXT DEFAULT CURRENT_TIMESTAMP,
  done_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_repairs_club ON data_repairs(club_id);
"""


def columns_for(field: str, include_geo: bool) -> tuple[str, ...]:
    """Which DB columns one orphan verdict clears."""
    if field == "oib":
        return REGISTRY_BUNDLE
    if field == "latlng":
        return GEO_BUNDLE if include_geo else ()
    return FIELDS_BY_NAME[field].repair_columns


def backup_db(db: Path, stamp: str, backup_dir: Path = BACKUP_DIR) -> Path:
    """Snapshot via the SQLite backup API — a plain file copy can catch a
    WAL-mode DB mid-write."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"clubs-{stamp}.db"
    src = sqlite3.connect(db)
    dst = sqlite3.connect(dest)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    log.info("backup written: %s (%.1f MB)", dest, dest.stat().st_size / 1e6)
    return dest


def load_verdicts(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--in-csv", type=Path, default=IN_CSV)
    ap.add_argument("--review-csv", type=Path, default=REVIEW_CSV)
    ap.add_argument("--execute", action="store_true",
                    help="Actually write. Without this flag nothing changes.")
    ap.add_argument("--include-geo", action="store_true",
                    help="Also NULL lat/lng for orphaned coordinates. Off by "
                         "default — shared pitches produce legitimate ties.")
    ap.add_argument("--stamp", default=None,
                    help="Backup filename timestamp. Defaults to now.")
    ap.add_argument("--backup-dir", type=Path, default=BACKUP_DIR)
    args = ap.parse_args()

    if not args.in_csv.exists():
        raise SystemExit(f"{args.in_csv} not found — run scripts/60_detect_collisions.py first")

    rows = load_verdicts(args.in_csv)
    orphans = [r for r in rows if r["verdict"] == "orphan"]
    ambiguous = [r for r in rows if r["verdict"] == "ambiguous"]
    log.info("verdicts: %d rows (%d orphan, %d ambiguous)",
             len(rows), len(orphans), len(ambiguous))

    # Review queue is written in both modes — it costs nothing and a dry run
    # should still hand the human something to look at.
    args.review_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.review_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(ambiguous)
    log.info("review queue: %s (%d rows)", args.review_csv, len(ambiguous))

    conn = connect(args.db)

    # Plan the work against live values first, so the dry run reports exactly
    # what --execute would do and re-running after a repair reports nothing.
    plan: list[dict] = []
    queue: dict[int, set[str]] = defaultdict(set)
    # `phone` and `phone_e164` are separate collision fields that clear the
    # same columns, so one club can be planned twice for one value. Collapse
    # on (club_id, column) — otherwise data_repairs logs a phantom second
    # repair whose old_value was already gone.
    planned: set[tuple[int, str]] = set()
    skipped_already_null = 0
    skipped_geo = 0

    for row in orphans:
        field = row["field"]
        cols = columns_for(field, args.include_geo)
        if not cols:
            skipped_geo += 1
            continue
        club_id = int(row["club_id"])
        current = conn.execute(
            f"SELECT {', '.join(cols)} FROM clubs WHERE id = ?", (club_id,)
        ).fetchone()
        if current is None:
            log.warning("club %d in CSV but not in DB — skipping", club_id)
            continue
        for col in cols:
            if (club_id, col) in planned:
                continue
            value = current[col]
            if value is None or (isinstance(value, str) and not value.strip()):
                skipped_already_null += 1
                continue
            planned.add((club_id, col))
            plan.append({
                "club_id": club_id,
                "slug": row["slug"],
                "column": col,
                "old_value": str(value),
                "reason": f"collision:{row['group_key']} score={row['owner_score']} "
                          f"verdict=orphan",
            })
            queue[club_id].add(col)

    by_col = Counter(p["column"] for p in plan)
    print()
    print(f"{'column':<22} {'values to NULL':>14}")
    print("-" * 38)
    for col, n in sorted(by_col.items(), key=lambda kv: -kv[1]):
        print(f"{col:<22} {n:>14}")
    print("-" * 38)
    print(f"{'clubs affected':<22} {len(queue):>14}")
    print(f"{'already NULL (no-op)':<22} {skipped_already_null:>14}")
    if skipped_geo:
        print(f"{'geo rows skipped':<22} {skipped_geo:>14}  (--include-geo to repair)")
    print()

    if not args.execute:
        log.info("DRY RUN — no changes written. Re-run with --execute to apply.")
        for p in plan[:15]:
            log.info("  would NULL %s.%s = %r", p["slug"], p["column"], p["old_value"][:60])
        if len(plan) > 15:
            log.info("  ... and %d more", len(plan) - 15)
        conn.close()
        return

    if not plan:
        log.info("nothing to repair — DB already clean for these verdicts")
        conn.close()
        return

    stamp = args.stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    conn.close()
    backup_db(args.db, stamp, args.backup_dir)
    conn = connect(args.db)

    conn.executescript(REPAIR_SCHEMA)
    for p in plan:
        conn.execute(
            f"UPDATE clubs SET {p['column']} = NULL, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (p["club_id"],),
        )
        conn.execute(
            "INSERT INTO data_repairs (club_id, field, old_value, new_value, reason) "
            "VALUES (?, ?, ?, NULL, ?)",
            (p["club_id"], p["column"], p["old_value"], p["reason"]),
        )

    for club_id, cols in queue.items():
        existing = conn.execute(
            "SELECT fields FROM backfill_queue WHERE club_id = ?", (club_id,)
        ).fetchone()
        merged = sorted(set(json.loads(existing["fields"])) | cols) if existing else sorted(cols)
        conn.execute(
            "INSERT INTO backfill_queue (club_id, fields, reason) VALUES (?, ?, ?) "
            "ON CONFLICT(club_id) DO UPDATE SET fields = excluded.fields, "
            "queued_at = CURRENT_TIMESTAMP, done_at = NULL",
            (club_id, json.dumps(merged), "namesake-leak quarantine"),
        )
    conn.commit()

    log.info("repaired: %d values across %d clubs; %d queued for re-backfill",
             len(plan), len(queue), len(queue))
    coverage = conn.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(phone_e164 IS NOT NULL) AS phone,
               SUM(email IS NOT NULL)      AS email,
               SUM(website IS NOT NULL)    AS website,
               SUM(fb_url IS NOT NULL)     AS fb,
               SUM(oib IS NOT NULL)        AS oib,
               SUM(president IS NOT NULL)  AS president
        FROM clubs
        """
    ).fetchone()
    log.info("post-repair coverage: total=%d phone_e164=%d email=%d website=%d "
             "fb=%d oib=%d president=%d",
             coverage["total"], coverage["phone"], coverage["email"],
             coverage["website"], coverage["fb"], coverage["oib"],
             coverage["president"])
    conn.close()


if __name__ == "__main__":
    main()
