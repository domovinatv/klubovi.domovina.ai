"""Discover Semafor URLs for top-tier clubs by crawling HNL/1.NL/2.NL standings.

The 172 pre-existing semafor_url values came from incidental Firecrawl hits
in the contact backfill — heavily skewed to amateur clubs. The top tiers
(SuperSport HNL, Prva NL, Druga NL) typically have proper club websites that
won out over Semafor in the Firecrawl ranking, so their semafor_url is mostly
empty. But Semafor for top-tier clubs is the JACKPOT: founded date, full
address, +385 phone, and lat/lng.

This script:
  1. Fetches the three big national-tier standings pages
  2. Extracts every /klubovi/{id}/{slug}/ link
  3. For each new (id, slug), fetches the club page and matches its
     canonical name + city against our DB
  4. Writes clubs.semafor_url where matched and the slot is empty
     (never overwrites a pre-existing semafor_url — those are already vetted)

Run scripts/17_ingest_semafor.py afterwards to pull the data in.
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402
from src.semafor import SemaforClient, canonical_url, parse_club_page  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("discover_semafor")

STANDINGS = [
    "https://semafor.hns.family/natjecanja/100391485/supersport-hnl/",
    "https://semafor.hns.family/natjecanja/100413651/supersport-prva-nl/",
    "https://semafor.hns.family/natjecanja/100418001/supersport-druga-nl/",
]

CLUB_LINK_RE = re.compile(r'/klubovi/(\d+)/([a-z0-9-]+)/')


def _norm_name(s: str | None) -> str:
    if not s:
        return ""
    s = s.lower()
    # Drop legal-form noise that varies by source.
    for marker in ("š. d. d.", "s. d. d.", " sdd", "š.d.d.", "s.d.d.", " š d d", " s d d"):
        s = s.replace(marker, "")
    # Drop leading "hrvatski nogometni klub", "nogometni klub", "građanski..."
    s = re.sub(r"\b(hrvatski |građanski |gradanski )?nogometni klub\b", "", s)
    s = re.sub(r"\b(hnk|gnk|nk|rnk|fk|znk|mnk)\b", "", s)
    # Drop single-letter parens suffix Semafor uses to disambiguate clubs in
    # the same city: "NK Trnje (Z)" -> drop "(Z)".
    s = re.sub(r"\(\s*[a-zšđčćž]\s*\)", " ", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _name_tokens(s: str) -> frozenset[str]:
    """Set of meaningful tokens after normalization, ignoring city-name dupes."""
    return frozenset(t for t in _norm_name(s).split() if len(t) > 1)


def discover_ids(client: SemaforClient) -> dict[int, str]:
    """Return {semafor_id: slug} from all standings pages."""
    found: dict[int, str] = {}
    for url in STANDINGS:
        log.info("crawling standings %s", url)
        # SemaforClient caches by club id only; for standings pages use raw fetch.
        resp = client._client.get(url)  # noqa: SLF001
        resp.raise_for_status()
        for m in CLUB_LINK_RE.finditer(resp.text):
            found[int(m.group(1))] = m.group(2)
    log.info("found %d unique club links across standings", len(found))
    return found


def run() -> None:
    matched = 0
    skipped_already = 0
    skipped_nomatch = 0
    with connect() as conn, SemaforClient() as sf:
        ids = discover_ids(sf)

        # Index our DB by city + token-set for tolerant matching.
        clubs = conn.execute(
            "SELECT id, canonical_name, city, semafor_url FROM clubs"
        ).fetchall()
        by_city: dict[str, list[dict]] = {}
        for c in clubs:
            city_key = (c["city"] or "").lower().strip()
            by_city.setdefault(city_key, []).append(dict(c))

        for sid, slug in ids.items():
            html = sf.fetch_html(sid)
            if html is None:
                continue
            parsed = parse_club_page(html)
            sf_short = parsed.get("short_name") or ""
            sf_full = parsed.get("full_name") or ""
            sf_city = ""
            if sf_full and "," in sf_full:
                sf_city = sf_full.rsplit(",", 1)[-1].strip().lower()
            # Take Semafor's name as just the part before the first comma in full_name
            sf_name_core = sf_full.split(",", 1)[0] if sf_full else sf_short
            sf_tokens = _name_tokens(sf_name_core) | _name_tokens(sf_short)
            # Tokens common to every club in this city are not discriminative
            # (e.g. city name itself).
            city_pool = by_city.get(sf_city, [])
            if sf_city:
                # remove the city name as a token
                sf_tokens = sf_tokens - _name_tokens(sf_city)

            candidates: list[dict] = []
            for c in city_pool:
                db_tokens = _name_tokens(c["canonical_name"]) - _name_tokens(sf_city)
                # Both name-modulo-city empty -> club is named after its city
                # (e.g. NK Opatija in Opatija). Accept iff only one candidate
                # in city — resolved after the loop.
                if not sf_tokens and not db_tokens:
                    candidates.append(c)
                    continue
                # One side empty, other non-empty: weak — reject to be safe.
                if not sf_tokens or not db_tokens:
                    continue
                # Otherwise: subset in either direction is good enough.
                if sf_tokens.issubset(db_tokens) or db_tokens.issubset(sf_tokens):
                    candidates.append(c)
                elif sf_tokens & db_tokens:
                    # Token overlap (e.g. both have "1991") — accept; we filter
                    # ambiguity by len(candidates) check below.
                    candidates.append(c)

            if not candidates:
                skipped_nomatch += 1
                log.warning(
                    "no DB match for semafor %d %s (short=%r full=%r city=%r tokens=%s)",
                    sid, slug, sf_short, sf_full, sf_city, sorted(sf_tokens),
                )
                continue
            if len(candidates) > 1:
                skipped_nomatch += 1
                log.warning(
                    "ambiguous DB match for semafor %d (%s, %s) -> %d candidates: %s",
                    sid, sf_short, sf_city, len(candidates),
                    [c["canonical_name"] for c in candidates],
                )
                continue

            club = candidates[0]
            if club["semafor_url"]:
                skipped_already += 1
                continue

            url = canonical_url(sid, slug)
            conn.execute(
                "UPDATE clubs SET semafor_url = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (url, club["id"]),
            )
            matched += 1
            log.info("matched semafor %d -> club %d %s", sid, club["id"], club["canonical_name"])

        conn.commit()

    log.info(
        "done: matched=%d already_had=%d unmatched=%d",
        matched, skipped_already, skipped_nomatch,
    )


if __name__ == "__main__":
    run()
