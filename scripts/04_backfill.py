"""General Firecrawl backfill runner.

Selects clubs from the DB matching CLI filters, runs backfill_club for each,
and prints per-field hit-rate stats at the end.

Examples:
  uv run python scripts/04_backfill.py --county "Zagrebačka županija"
  uv run python scripts/04_backfill.py --tier 1 --tier 2
  uv run python scripts/04_backfill.py --limit 5
  uv run python scripts/04_backfill.py --county "Grad Zagreb" --skip-filled
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.backfill import backfill_club  # noqa: E402
from src.db import connect  # noqa: E402
from src.firecrawl import FirecrawlClient  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("backfill")

CONTACT_COLS = (
    "city", "address", "email", "phone", "website",
    "fb_url", "ig_url", "x_url", "president",
    "stadium_name", "founded_year",
)


def select_clubs(conn, args) -> list[dict]:
    sql = ["SELECT DISTINCT c.* FROM clubs c"]
    where: list[str] = []
    params: list = []
    if args.tier:
        sql.append("JOIN club_seasons cs ON cs.club_id = c.id "
                   "JOIN leagues l ON l.id = cs.league_id")
        placeholders = ",".join(["?"] * len(args.tier))
        where.append(f"l.tier IN ({placeholders})")
        params.extend(args.tier)
    if args.county:
        where.append("c.county = ?")
        params.append(args.county)
    if args.skip_filled:
        # Skip clubs that already have email or phone.
        where.append("(c.email IS NULL AND c.phone IS NULL)")
    if where:
        sql.append("WHERE " + " AND ".join(where))
    sql.append("ORDER BY c.canonical_name")
    if args.limit:
        sql.append(f"LIMIT {int(args.limit)}")
    rows = conn.execute(" ".join(sql), params).fetchall()
    return [dict(r) for r in rows]


def hit_rate_report(conn, club_ids: list[int]) -> None:
    if not club_ids:
        return
    placeholders = ",".join(["?"] * len(club_ids))
    row = conn.execute(
        f"SELECT {', '.join(CONTACT_COLS)} FROM clubs WHERE id IN ({placeholders})",
        club_ids,
    ).fetchall()
    log.info("-" * 60)
    log.info("Hit-rate after backfill (n=%d):", len(row))
    for col in CONTACT_COLS:
        filled = sum(1 for r in row if r[col] not in (None, "", 0))
        pct = 100.0 * filled / len(row)
        log.info("  %-18s %4d / %d  (%5.1f%%)", col, filled, len(row), pct)


def run() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--county", help="Exact county name (e.g. 'Zagrebačka županija')")
    p.add_argument("--tier", type=int, action="append", help="Tier filter; repeatable")
    p.add_argument("--limit", type=int, help="Max clubs to process")
    p.add_argument("--skip-filled", action="store_true",
                   help="Skip clubs that already have email or phone")
    args = p.parse_args()

    with connect() as conn, FirecrawlClient() as client:
        clubs = select_clubs(conn, args)
        log.info("selected %d clubs", len(clubs))

        statuses: dict[str, int] = {}
        for i, c in enumerate(clubs, 1):
            log.info("[%d/%d] %s", i, len(clubs), c["canonical_name"])
            try:
                res = backfill_club(conn, client, c)
            except Exception as e:
                log.exception("error on %s: %s", c["canonical_name"], e)
                statuses["exception"] = statuses.get("exception", 0) + 1
                continue
            statuses[res["status"]] = statuses.get(res["status"], 0) + 1
            conn.commit()

        log.info("=" * 60)
        log.info("Done. Credits used: %d. Status breakdown: %s",
                 client.credits_used, statuses)
        hit_rate_report(conn, [c["id"] for c in clubs])


if __name__ == "__main__":
    run()
