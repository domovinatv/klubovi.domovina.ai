"""One-shot SQL cleanup of systemic data leaks identified by the 2026-05-17
verification audit.

Applies these passes in order:

  1. ALTER TABLE clubs ADD COLUMN semafor_url (if missing).
  2. Move every `website` that points at `semafor.hns.family` into the new
     `semafor_url` column — Semafor profile pages aren't club-owned sites
     but the link itself is canonical HNS, worth keeping.
  3. Clear `fb_url` and `x_url` that are Facebook/Twitter share-button URLs
     (carryover from before the share-link filter was added to
     `src/backfill.py:score_url`).
  4. Clear `stadium_name` where it equals `canonical_name` — JSON extraction
     leak.
  5. Clear `website` matching known aggregator / FA / news domains.
  6. Clear `email` on FA-domain hosts.
  7. Clear any contact field whose value is shared across >1 club in the DB
     (e.g. nogometni.klub.borac@ri.t-com.hr appears on 7 clubs — only one is
     real, but we can't tell which; let the targeted re-backfill restore the
     canonical one).

Idempotent: re-runs after the same row state will simply find 0 matches.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cleanup_leaks")


def ensure_column(conn) -> None:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(clubs)").fetchall()}
    if "semafor_url" not in cols:
        conn.execute("ALTER TABLE clubs ADD COLUMN semafor_url TEXT")
        log.info("added column semafor_url")


def run() -> None:
    with connect() as conn:
        ensure_column(conn)

        # 1. Move Semafor URLs out of website into semafor_url.
        n = conn.execute(
            "UPDATE clubs "
            "SET semafor_url = website, website = NULL, "
            "    updated_at = CURRENT_TIMESTAMP "
            "WHERE website LIKE '%semafor.hns.family%'"
        ).rowcount
        log.info("moved %d websites to semafor_url", n)

        # 2. Share-button URLs in fb_url / x_url.
        n = conn.execute(
            "UPDATE clubs SET fb_url = NULL, updated_at = CURRENT_TIMESTAMP "
            "WHERE fb_url LIKE '%/sharer%' OR fb_url LIKE '%/share%' "
            "   OR fb_url LIKE '%/dialog%' OR fb_url LIKE '%intent/share%'"
        ).rowcount
        log.info("cleared %d sharer-style fb_url values", n)
        n = conn.execute(
            "UPDATE clubs SET x_url = NULL, updated_at = CURRENT_TIMESTAMP "
            "WHERE x_url LIKE '%twitter.com/share%' OR x_url LIKE '%intent/tweet%'"
        ).rowcount
        log.info("cleared %d sharer-style x_url values", n)

        # 3. stadium_name = canonical_name (JSON extract picked the club name).
        n = conn.execute(
            "UPDATE clubs SET stadium_name = NULL, updated_at = CURRENT_TIMESTAMP "
            "WHERE stadium_name = canonical_name"
        ).rowcount
        log.info("cleared %d stadium_name = canonical_name leaks", n)

        # 4. Known aggregator / news / FA-aggregator websites.
        bad_website_likes = [
            "%hrvatskekarta.com%",
            "%dugoselska-kronika%",
            "%poslovna.hr%",
            "%companywall.hr%",
            "%sudreg.hr%",
            "%fina.hr%",
            "%boniteti.hr%",
            "%nszz.hr%",
            "%nssmz.hr%",
            "%nssloga-cakovec.hr%",
            "%nszns.hr%",
        ]
        clauses = " OR ".join("website LIKE ?" for _ in bad_website_likes)
        n = conn.execute(
            f"UPDATE clubs SET website = NULL, updated_at = CURRENT_TIMESTAMP "
            f"WHERE {clauses}",
            bad_website_likes,
        ).rowcount
        log.info("cleared %d aggregator/news/FA websites", n)

        # 5. FA-domain emails.
        n = conn.execute(
            "UPDATE clubs SET email = NULL, updated_at = CURRENT_TIMESTAMP "
            "WHERE email LIKE '%@nszz.%' OR email LIKE '%@nszns.%' "
            "   OR email LIKE '%@nssmz%' OR email LIKE '%@nssloga%' "
            "   OR email LIKE '%@savez%' OR email LIKE '%@hns.%' "
            "   OR email LIKE 'tajnik@%' OR email LIKE 'ured@%'"
        ).rowcount
        log.info("cleared %d FA-pattern emails", n)

        # 6. Cross-club duplicates: any field value shared across >1 club is
        # almost certainly leak. Clear all and let re-backfill restore.
        for col in ("email", "phone", "phone_e164", "website", "fb_url"):
            n = conn.execute(
                f"""
                UPDATE clubs SET {col} = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE {col} IN (
                    SELECT {col} FROM clubs
                    WHERE {col} IS NOT NULL
                    GROUP BY {col}
                    HAVING COUNT(*) > 1
                )
                """
            ).rowcount
            log.info("cleared %d cross-club shared %s values", n, col)

        # Phone classification: if phone got cleared, kind/e164 must follow.
        conn.execute(
            "UPDATE clubs SET phone_kind = NULL, phone_e164 = NULL "
            "WHERE phone IS NULL AND (phone_kind IS NOT NULL OR phone_e164 IS NOT NULL)"
        )

        conn.commit()

        # Final report.
        row = conn.execute(
            """
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN phone IS NOT NULL THEN 1 ELSE 0 END) AS phone,
              SUM(CASE WHEN email IS NOT NULL THEN 1 ELSE 0 END) AS email,
              SUM(CASE WHEN website IS NOT NULL THEN 1 ELSE 0 END) AS website,
              SUM(CASE WHEN fb_url IS NOT NULL THEN 1 ELSE 0 END) AS fb,
              SUM(CASE WHEN semafor_url IS NOT NULL THEN 1 ELSE 0 END) AS semafor
            FROM clubs
            """
        ).fetchone()
        log.info(
            "post-cleanup: total=%d phone=%d email=%d website=%d fb=%d semafor=%d",
            row["total"], row["phone"], row["email"], row["website"],
            row["fb"], row["semafor"],
        )


if __name__ == "__main__":
    run()
