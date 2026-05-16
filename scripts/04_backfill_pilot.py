"""Firecrawl backfill pilot on a fixed mix of clubs across tiers.

Picks the alphabetically-first club from each tier present in the DB, runs the
full search + scrape pipeline, and prints a per-club report at the end. Use
this to gauge precision and credit cost before scaling to the full ~900 clubs.
"""
from __future__ import annotations

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
log = logging.getLogger("backfill_pilot")


def pick_pilot_clubs(conn) -> list[dict]:
    """Two clubs per tier (1, 4, 6, 8) — variety across pro/amateur."""
    targets: list[dict] = []
    for tier in (1, 4, 6, 8):
        rows = conn.execute(
            """
            SELECT DISTINCT c.*
            FROM clubs c
            JOIN club_seasons cs ON cs.club_id = c.id
            JOIN leagues l ON l.id = cs.league_id
            WHERE l.tier = ?
            ORDER BY c.canonical_name
            LIMIT 3
            """,
            (tier,),
        ).fetchall()
        for r in rows[:2]:
            d = dict(r)
            d["_tier"] = tier
            targets.append(d)
    return targets


def run() -> None:
    with connect() as conn, FirecrawlClient() as client:
        pilots = pick_pilot_clubs(conn)
        log.info("pilot clubs: %d", len(pilots))

        results: list[dict] = []
        for c in pilots:
            log.info("--- tier=%d  %s ---", c["_tier"], c["canonical_name"])
            res = backfill_club(conn, client, c)
            res["_tier"] = c["_tier"]
            results.append(res)
            conn.commit()

        log.info("=" * 60)
        log.info("Pilot summary  (credits used: %d)", client.credits_used)
        log.info("=" * 60)
        for r in results:
            fields = r.get("fields", [])
            log.info(
                "tier=%d  %-30s  status=%s  filled=%d (%s)",
                r["_tier"], r["name"], r["status"], len(fields), ", ".join(fields),
            )

        # Show full state of each pilot club after backfill.
        log.info("-" * 60)
        log.info("Post-backfill rows:")
        for r in results:
            row = dict(conn.execute(
                "SELECT canonical_name, city, county, website, email, phone, "
                "fb_url, ig_url, x_url, president, stadium_name, founded_year "
                "FROM clubs WHERE id = ?",
                (r["club_id"],),
            ).fetchone())
            log.info("  %s:", row["canonical_name"])
            for k, v in row.items():
                if k == "canonical_name" or not v:
                    continue
                log.info("    %-16s %s", k, v)


if __name__ == "__main__":
    run()
