"""Ingest phone / email / website from each club's Facebook Page About page.

For every clubs.fb_url, fetch the /about_contact_and_basic_info markdown via
Firecrawl (the only path that bypasses Facebook's login wall reliably) and
parse the Contact info / Websites sections.

Trust hierarchy — Facebook wins only where it adds something and the slot is
empty. Never overwrite a curated value:

  phone   FILL if current is NULL. Run src.phones.to_e164/classify on the
          parsed value so phone_e164 + phone_kind also land.
  email   FILL if current is NULL.
  website FILL if current is NULL AND the parsed URL is not a FB / IG / news
          domain (filter already applied in src.facebook).

Idempotent. Per-key Firecrawl credit usage logged at start + end.

Usage:
  uv run python scripts/20_ingest_facebook_about.py [--limit N]

The --limit cap is useful for a probe run before committing the full set.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402
from src.facebook import canonical_about_url, scrape_about  # noqa: E402
from src.firecrawl import FirecrawlClient, InsufficientCreditsError  # noqa: E402
from src.phones import classify, to_e164  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest_fb")


def run(limit: int | None = None) -> None:
    counts = {
        "rows": 0,
        "scraped": 0,
        "skipped_bad_url": 0,
        "phone_filled": 0,
        "email_filled": 0,
        "website_filled": 0,
        "fb_with_no_contact": 0,
    }

    with connect() as conn, FirecrawlClient() as fc:
        balances = fc.credits_across_keys()
        log.info("starting balances: %s", ", ".join(f"{k}={c}" for k, c in balances))
        total_start = sum(c or 0 for _, c in balances)

        sql = (
            "SELECT id, canonical_name, fb_url, phone, email, website "
            "FROM clubs WHERE fb_url IS NOT NULL ORDER BY id"
        )
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = conn.execute(sql).fetchall()
        log.info("processing %d clubs with fb_url", len(rows))

        for r in rows:
            counts["rows"] += 1
            if canonical_about_url(r["fb_url"]) is None:
                counts["skipped_bad_url"] += 1
                continue
            try:
                parsed = scrape_about(fc, r["fb_url"])
            except InsufficientCreditsError:
                log.warning("all keys out of credits at row %d; stopping early", r["id"])
                break
            except RuntimeError as exc:
                log.warning("scrape failed for club %d: %s", r["id"], exc)
                continue
            if parsed is None:
                counts["skipped_bad_url"] += 1
                continue
            counts["scraped"] += 1

            updates: dict[str, object] = {}

            if r["phone"] is None and parsed.get("phone"):
                phone_raw = parsed["phone"]
                e164 = to_e164(phone_raw)
                if e164:
                    updates["phone"] = phone_raw
                    updates["phone_e164"] = e164
                    updates["phone_kind"] = classify(phone_raw)
                    counts["phone_filled"] += 1

            if r["email"] is None and parsed.get("email"):
                updates["email"] = parsed["email"]
                counts["email_filled"] += 1

            if r["website"] is None and parsed.get("website"):
                updates["website"] = parsed["website"]
                counts["website_filled"] += 1

            if not (parsed.get("phone") or parsed.get("email") or parsed.get("website")):
                counts["fb_with_no_contact"] += 1

            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE clubs SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    [*updates.values(), r["id"]],
                )

            if counts["rows"] % 25 == 0:
                conn.commit()
                log.info(
                    "progress %d/%d  phone=%d email=%d web=%d  credits_used=%d",
                    counts["rows"], len(rows),
                    counts["phone_filled"], counts["email_filled"],
                    counts["website_filled"], fc.credits_used,
                )

        conn.commit()
        balances_end = fc.credits_across_keys()
        total_end = sum(c or 0 for _, c in balances_end)
        log.info("ending balances: %s", ", ".join(f"{k}={c}" for k, c in balances_end))
        log.info("credit spend this run: %d (firecrawl reported %d used)",
                 total_start - total_end, fc.credits_used)

    log.info("done: %s", counts)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="stop after N rows (probe)")
    args = ap.parse_args()
    run(args.limit)
