"""Backfill clubs.county for hrnogomet-sourced clubs.

The /team-standings endpoint only gives team id + name. /teams/{id} adds
countyId / leagueName / seasonName. We resolve countyId -> county name via the
cached /county/leagues payload, then UPDATE clubs.county.

Idempotent: skips clubs already enriched (county IS NOT NULL).
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402
from src.hrnogomet import HRNogometClient, build_county_map  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("enrich_counties")


def run() -> None:
    with connect() as conn, HRNogometClient() as client:
        county_map = build_county_map(client.county_leagues())
        log.info("loaded %d county entities", len(county_map))

        rows = conn.execute(
            """
            SELECT DISTINCT c.id, c.canonical_name, a.alias AS hrnogomet_id
            FROM clubs c
            JOIN club_aliases a ON a.club_id = c.id
            WHERE a.source = 'hrnogomet-id'
              AND (c.county IS NULL OR c.county = '')
            """
        ).fetchall()
        log.info("clubs needing county enrichment: %d", len(rows))

        updated = 0
        for i, row in enumerate(rows, 1):
            try:
                team = client.team(int(row["hrnogomet_id"]))
            except (RuntimeError, ValueError) as e:
                log.warning("skip club %s (id=%s): %s", row["canonical_name"], row["id"], e)
                continue
            county_id = team.get("countyId")
            county_name = county_map.get(county_id) if county_id is not None else None
            if county_name:
                conn.execute(
                    "UPDATE clubs SET county = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (county_name, row["id"]),
                )
                updated += 1
            if i % 50 == 0:
                conn.commit()
                log.info("progress: %d/%d (updated=%d)", i, len(rows), updated)
        conn.commit()

        # Coverage by county after enrichment.
        log.info("done. county updates: %d", updated)
        breakdown = conn.execute(
            "SELECT COALESCE(county, '<none>') AS county, COUNT(*) AS n "
            "FROM clubs GROUP BY county ORDER BY n DESC"
        ).fetchall()
        for r in breakdown:
            log.info("  %-40s %4d", r["county"], r["n"])


if __name__ == "__main__":
    run()
