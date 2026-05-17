"""Populate clubs.sofascore_url from the `sofascore-id` alias.

Idempotent: re-runs are cheap. Re-run whenever scripts/15 adds new aliases.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sofascore_url")

URL_TEMPLATE = "https://www.sofascore.com/team/football/-/{}"


def ensure_column(conn) -> None:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(clubs)").fetchall()}
    if "sofascore_url" not in cols:
        conn.execute("ALTER TABLE clubs ADD COLUMN sofascore_url TEXT")
        log.info("added column sofascore_url")


def run() -> None:
    with connect() as conn:
        ensure_column(conn)
        rows = conn.execute(
            """
            SELECT c.id, a.alias AS sid
            FROM clubs c
            JOIN club_aliases a ON a.club_id = c.id AND a.source = 'sofascore-id'
            """
        ).fetchall()
        n = 0
        for r in rows:
            url = URL_TEMPLATE.format(r["sid"])
            cur = conn.execute(
                "UPDATE clubs SET sofascore_url = ? "
                "WHERE id = ? AND (sofascore_url IS NULL OR sofascore_url != ?)",
                (url, r["id"], url),
            )
            if cur.rowcount:
                n += 1
        conn.commit()
        total = conn.execute(
            "SELECT COUNT(*) FROM clubs WHERE sofascore_url IS NOT NULL"
        ).fetchone()[0]
        log.info("rows updated: %d  total with sofascore_url: %d", n, total)


if __name__ == "__main__":
    run()
