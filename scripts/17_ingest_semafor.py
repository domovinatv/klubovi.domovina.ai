"""Ingest data from per-club semafor.hns.family pages into the clubs table.

Source of truth: every clubs.semafor_url (172 of them at time of writing,
discovered incidentally by the Firecrawl contact backfill and moved into
this column by scripts/14_cleanup_leaks.py).

Trust hierarchy — Semafor wins only for fields it is canonical for, and
only where the current value is missing or a known leak:

  stadium_name   OVERWRITE if (current is NULL) or (current == canonical_name)
  founded_year   FILL if current is NULL
  address        FILL if current is NULL
  phone          FILL if current is NULL AND Semafor phone is international
                 (+385 prefix → top tier, vetted format). Local-format amateur
                 phones are skipped to avoid noisy E.164 conversion.
  lat / lng      FILL if both currently NULL (don't fight the geocoder)

Never touched: canonical_name, city, county, email, website, social URLs,
president, sofascore_url. Those columns are curated elsewhere.

Idempotent. Honest. Reports per-field deltas.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402
from src.phones import classify, to_e164  # noqa: E402
from src.semafor import SemaforClient, extract_club_id  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest_semafor")


def _is_leak(stadium: str | None, canonical: str) -> bool:
    """stadium_name == canonical_name was the JSON-extraction leak pattern."""
    return stadium is not None and stadium.strip() == canonical.strip()


def run() -> None:
    counts = {
        "fetched": 0,
        "missing_page": 0,
        "stadium_filled": 0,
        "stadium_corrected": 0,
        "founded_filled": 0,
        "address_filled": 0,
        "phone_filled": 0,
        "geo_filled": 0,
    }

    with connect() as conn, SemaforClient() as sf:
        rows = conn.execute(
            """
            SELECT id, canonical_name, stadium_name, founded_year, address,
                   phone, phone_e164, phone_kind, lat, lng, semafor_url
            FROM clubs
            WHERE semafor_url IS NOT NULL
            ORDER BY id
            """
        ).fetchall()
        log.info("processing %d clubs with semafor_url", len(rows))

        for r in rows:
            if extract_club_id(r["semafor_url"]) is None:
                log.warning(
                    "skipping club %d (%s) — semafor_url has no /klubovi/{id}/: %s",
                    r["id"], r["canonical_name"], r["semafor_url"],
                )
                counts["missing_page"] += 1
                continue
            parsed = sf.fetch_parsed(r["semafor_url"])
            if parsed is None:
                counts["missing_page"] += 1
                log.warning("404 for club %d (%s) at %s", r["id"], r["canonical_name"], r["semafor_url"])
                continue
            counts["fetched"] += 1

            updates: dict[str, object] = {}

            # stadium_name: overwrite NULL or leak
            sf_stadium = parsed.get("stadium_name")
            if sf_stadium:
                if r["stadium_name"] is None:
                    updates["stadium_name"] = sf_stadium
                    counts["stadium_filled"] += 1
                elif _is_leak(r["stadium_name"], r["canonical_name"]):
                    updates["stadium_name"] = sf_stadium
                    counts["stadium_corrected"] += 1

            # founded_year: fill only
            if r["founded_year"] is None and parsed.get("founded_year"):
                updates["founded_year"] = parsed["founded_year"]
                counts["founded_filled"] += 1

            # address: fill only
            if r["address"] is None and parsed.get("address"):
                updates["address"] = parsed["address"]
                counts["address_filled"] += 1

            # phone: fill only when Semafor gives international format
            sf_phone = parsed.get("phone")
            if (
                r["phone"] is None
                and sf_phone
                and (sf_phone.startswith("+385") or sf_phone.startswith("00385"))
            ):
                kind = classify(sf_phone)
                e164 = to_e164(sf_phone)
                if e164:
                    updates["phone"] = sf_phone
                    updates["phone_kind"] = kind
                    updates["phone_e164"] = e164
                    counts["phone_filled"] += 1

            # lat/lng: fill only if both missing
            if (
                r["lat"] is None
                and r["lng"] is None
                and parsed.get("lat") is not None
                and parsed.get("lng") is not None
            ):
                updates["lat"] = parsed["lat"]
                updates["lng"] = parsed["lng"]
                counts["geo_filled"] += 1

            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE clubs SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    [*updates.values(), r["id"]],
                )

        conn.commit()

    log.info("done: %s", counts)


if __name__ == "__main__":
    run()
