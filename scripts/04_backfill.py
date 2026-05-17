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
from src.firecrawl import FirecrawlClient, InsufficientCreditsError  # noqa: E402

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
    if args.unprocessed:
        # Skip any club that has ever been touched by a backfill_runs entry,
        # even if that run filled zero fields. Avoids burning credits on
        # already-attempted clubs whose external data is simply absent.
        where.append("c.id NOT IN (SELECT DISTINCT club_id FROM backfill_runs)")
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
    p.add_argument("--unprocessed", action="store_true",
                   help="Skip clubs that already have a backfill_runs entry")
    args = p.parse_args()

    with connect() as conn, FirecrawlClient() as client:
        clubs = select_clubs(conn, args)
        balances = client.credits_across_keys()
        starting_balance = balances[0][1] if balances else None
        log.info("selected %d clubs   keys: %s",
                 len(clubs),
                 ", ".join(f"{n}={c}" for n, c in balances))

        statuses: dict[str, int] = {}
        stopped_early = False
        processed_ids: list[int] = []
        for i, c in enumerate(clubs, 1):
            log.info("[%d/%d] %s", i, len(clubs), c["canonical_name"])
            try:
                res = backfill_club(conn, client, c)
            except InsufficientCreditsError as e:
                log.warning("OUT OF CREDITS at club %d/%d: %s", i, len(clubs), e)
                stopped_early = True
                conn.commit()
                break
            except Exception as e:
                log.exception("error on %s: %s", c["canonical_name"], e)
                statuses["exception"] = statuses.get("exception", 0) + 1
                continue
            statuses[res["status"]] = statuses.get(res["status"], 0) + 1
            processed_ids.append(c["id"])
            conn.commit()
            if i % 25 == 0:
                bal = client.remaining_credits()
                log.info("  ... %d/%d processed. remaining credits: %s",
                         i, len(clubs), bal)

        ending_balance = client.remaining_credits()
        log.info("=" * 60)
        log.info("Done %s. processed=%d  status=%s  spent=%s  remaining=%s",
                 "(stopped on out-of-credits)" if stopped_early else "(all clubs)",
                 len(processed_ids), statuses,
                 (starting_balance - ending_balance) if starting_balance and ending_balance else "?",
                 ending_balance)
        hit_rate_report(conn, processed_ids)


if __name__ == "__main__":
    run()
