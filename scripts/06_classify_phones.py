"""One-shot migration: add phone_kind/phone_e164 columns and populate them.

Idempotent: skips columns that already exist; re-classifies every non-null
phone on each run (cheap).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402
from src.phones import classify, to_e164  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("classify_phones")


def ensure_columns(conn) -> None:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(clubs)").fetchall()}
    if "phone_kind" not in cols:
        conn.execute("ALTER TABLE clubs ADD COLUMN phone_kind TEXT")
        log.info("added column phone_kind")
    if "phone_e164" not in cols:
        conn.execute("ALTER TABLE clubs ADD COLUMN phone_e164 TEXT")
        log.info("added column phone_e164")


def run() -> None:
    with connect() as conn:
        ensure_columns(conn)
        rows = conn.execute(
            "SELECT id, phone FROM clubs WHERE phone IS NOT NULL"
        ).fetchall()
        counters = {"mobile": 0, "landline": 0, "unknown": 0}
        for r in rows:
            kind = classify(r["phone"])
            e164 = to_e164(r["phone"])
            conn.execute(
                "UPDATE clubs SET phone_kind = ?, phone_e164 = ? WHERE id = ?",
                (kind, e164, r["id"]),
            )
            counters[kind] += 1
        conn.commit()
        log.info("classified %d phones: %s", len(rows), counters)


if __name__ == "__main__":
    run()
