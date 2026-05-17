"""Second-pass cleanup of leak classes surfaced by verification Run 4 (seed 23251).

Three systemic leak patterns the original `scripts/14_cleanup_leaks.py` did
not catch, all confirmed by counting in the DB before nulling:

  1. **Twitter `/home?status=` share-intent URLs in `x_url`.**
     These are the "Share this page on Twitter" buttons embedded on Semafor
     club pages — they compose a tweet with the Semafor URL as content. None
     are real club Twitter handles. Cleanup 14 blocked `/share` and
     `/intent/tweet` but not this third shape. Affects ~155 rows.

  2. **Municipal-office email contamination** — `opcina@`, `opcina.X@`,
     `financije@` local-parts; addresses on `opcina-X.hr` / `X-opcina.hr`
     domains. Surfaced on NK Trnski (Općina Nova Rača) and NK Psunj Sokol
     (Općina Okučani) but extends to ~7 emails + 6 websites total.

  3. **Municipal-page-as-website** — `nova-raca.hr/`, `opcokucani.tcloud.hr`,
     `opcina-orle.hr/nogometni-klub-X/` etc. The page may legitimately link
     TO the club but is the municipality's site, not a club site.

Cross-county leaks (e.g. NK Poljana SMŽ holding Poljana Požega's contact)
are intentionally NOT auto-nulled here — area-code/postcode checks have
too many false positives in a DB where 217 mobile numbers carry no area
context and clubs near county borders legitimately use neighbouring
landlines. That class is better handled by the next backfill pass with a
similarity gate (see src/backfill.py update in this commit).

Idempotent. Counts before + after.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cleanup_v2")


# Municipal markers — narrow on purpose. Each token here triggered a real
# leak in the DB at audit time; we resist adding generic words like "grad"
# that appear in legitimate club domains (NK Gradina, NK Gradac, ...).
_MUNICIPAL_DOMAIN_PATTERNS = [
    "%opcina-%",   # opcina-orle.hr, opcina-velika.hr, opcina-sikirevci.hr
    "%-opcina%",   # X-opcina.hr
    "%opcine-%",   # opcine-X (plural form occasionally seen)
    "%opcokucani%",
    "%nova-raca%",
    "%opcina-negoslavci%",
]

_MUNICIPAL_EMAIL_LOCAL_PARTS = [
    "opcina@%",
    "opcina.%@%",
    "financije@%",
    "racunovod%@%",
    "pisarnic%@%",
]


def run() -> None:
    with connect() as conn:
        # 1. Twitter /home?status= share-intent URLs in x_url.
        n = conn.execute(
            "UPDATE clubs SET x_url = NULL, updated_at = CURRENT_TIMESTAMP "
            "WHERE x_url LIKE '%twitter.com/home?status=%' "
            "   OR x_url LIKE '%twitter.com/%?status=%' "
            "   OR x_url LIKE '%/intent/tweet%'"
        ).rowcount
        log.info("cleared %d twitter share-intent x_url values", n)

        # 1b. Same pattern occasionally lands in fb_url too (compose dialog).
        n = conn.execute(
            "UPDATE clubs SET fb_url = NULL, updated_at = CURRENT_TIMESTAMP "
            "WHERE fb_url LIKE '%facebook.com/%?status=%' "
            "   OR fb_url LIKE '%/dialog/feed%' "
            "   OR fb_url LIKE 'fb-messenger://%'"
        ).rowcount
        log.info("cleared %d facebook share-intent fb_url values", n)

        # 2. Municipal-office emails.
        clauses = " OR ".join("email LIKE ?" for _ in _MUNICIPAL_EMAIL_LOCAL_PARTS)
        n = conn.execute(
            f"UPDATE clubs SET email = NULL, updated_at = CURRENT_TIMESTAMP "
            f"WHERE {clauses}",
            _MUNICIPAL_EMAIL_LOCAL_PARTS,
        ).rowcount
        log.info("cleared %d municipal-office email values", n)

        # 3. Municipal websites — domain-level match.
        clauses = " OR ".join("website LIKE ?" for _ in _MUNICIPAL_DOMAIN_PATTERNS)
        n = conn.execute(
            f"UPDATE clubs SET website = NULL, updated_at = CURRENT_TIMESTAMP "
            f"WHERE {clauses}",
            _MUNICIPAL_DOMAIN_PATTERNS,
        ).rowcount
        log.info("cleared %d municipal-domain website values", n)

        # 3b. When website cleared because municipal, phone/email on the same
        # row often came from the same scrape — null them too IF they don't
        # appear on another club's row (so we don't lose a real club's value).
        # Approach: collect ids that just lost website, then null phone where
        # the phone number isn't used elsewhere.
        # (At this point websites for municipal hits are already NULL; we
        # cleared 13 rows total. Anything attached to those rows is suspect.)
        # Keep it simple: leave phones in place. The cross-club-duplicate
        # cleanup in scripts/14 already handled the worst cross-row sharing.
        # Manual / next-iteration backfill will overwrite phones where needed.

        conn.commit()

        # Final coverage report so a re-run is comparable.
        row = conn.execute(
            """
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN phone IS NOT NULL THEN 1 ELSE 0 END) AS phone,
              SUM(CASE WHEN email IS NOT NULL THEN 1 ELSE 0 END) AS email,
              SUM(CASE WHEN website IS NOT NULL THEN 1 ELSE 0 END) AS website,
              SUM(CASE WHEN fb_url IS NOT NULL THEN 1 ELSE 0 END) AS fb,
              SUM(CASE WHEN x_url IS NOT NULL THEN 1 ELSE 0 END) AS x,
              SUM(CASE WHEN semafor_url IS NOT NULL THEN 1 ELSE 0 END) AS semafor
            FROM clubs
            """
        ).fetchone()
        log.info(
            "post-cleanup: total=%d phone=%d email=%d website=%d fb=%d x=%d semafor=%d",
            row["total"], row["phone"], row["email"], row["website"],
            row["fb"], row["x"], row["semafor"],
        )


if __name__ == "__main__":
    run()
