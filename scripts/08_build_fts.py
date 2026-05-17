"""Build the clubs_fts virtual table for full-text search.

FTS5 with unicode61 tokenizer and diacritics removal so a query for
"djakovo" also matches "Đakovo", "Sibenik" matches "Šibenik" etc.

Idempotent: drops + recreates the table on each run. Triggers aren't
necessary because all club inserts go through batch ingest scripts and
this is fast enough to re-run after each one.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402
from src.normalize import strip_diacritics  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build_fts")

FTS_SCHEMA = """
DROP TABLE IF EXISTS clubs_fts;
CREATE VIRTUAL TABLE clubs_fts USING fts5(
  slug UNINDEXED,
  name,
  short_name,
  city,
  address,
  aliases,
  tokenize = "unicode61 remove_diacritics 2"
);
"""


def run() -> None:
    with connect() as conn:
        conn.executescript(FTS_SCHEMA)
        rows = conn.execute(
            """
            SELECT
              c.slug,
              c.canonical_name,
              COALESCE(c.short_name, '')                AS short_name,
              COALESCE(c.city, '')                      AS city,
              COALESCE(c.address, '')                   AS address,
              COALESCE(GROUP_CONCAT(a.alias, ' '), '')  AS aliases
            FROM clubs c
            LEFT JOIN club_aliases a
              ON a.club_id = c.id AND a.source NOT LIKE '%-id'
            GROUP BY c.id
            """
        ).fetchall()
        # FTS5's unicode61 tokenizer doesn't decompose Đ/đ (same blind spot as
        # our slug normalizer). Run every field through strip_diacritics so
        # that querying for "Dakovo" / "djakovo" finds "Đakovo".
        def _norm(s: str) -> str:
            return strip_diacritics(s or "").lower()

        conn.executemany(
            "INSERT INTO clubs_fts (slug, name, short_name, city, address, aliases) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (r["slug"], _norm(r["canonical_name"]), _norm(r["short_name"]),
                 _norm(r["city"]), _norm(r["address"]), _norm(r["aliases"]))
                for r in rows
            ],
        )
        conn.commit()
        log.info("indexed %d clubs into clubs_fts", len(rows))


if __name__ == "__main__":
    run()
