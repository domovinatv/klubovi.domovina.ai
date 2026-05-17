"""Full BFS crawl of Semafor: discover every actively-competing Croatian
football club listed in the system, then match them against our DB.

Discovery mechanic (no sitemap exists):
  - Seed = national standings on the homepage + every `cid=` we already
    have cached from previously-fetched club pages.
  - For each unseen competition id, fetch its standings page; the rendered
    table contains `/klubovi/{id}/{slug}/` links — these are the
    participating clubs.
  - For each unseen club, fetch its profile; the page embeds the cid(s)
    for the league(s) it currently competes in. Push those onto the queue.
  - Stop when no new cids or club ids are discovered.

The queue typically saturates after ~1 minute: 1.HNL → 12 club pages →
20+ county-level "Druga NSZŽ" / "Treća NSZŽ" cids → most of the amateur
universe.

After discovery, match each Semafor club to our DB by (city, token
overlap on canonical_name) and write `clubs.semafor_url` where we have
confidence and the slot is empty.

Cache:
  data/raw/semafor/{club_id}.html        (shared with scripts/17, 17b)
  data/raw/semafor/standings/{cid}.html  (new — kept across runs)

Re-runnable: cached files mean repeat runs are near-instant; only pages
that 404'd previously get refetched (we don't cache empties).
"""
from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path
from typing import Iterable

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402
from src.semafor import (  # noqa: E402
    BASE_URL,
    HEADERS,
    SemaforClient,
    canonical_url,
    parse_club_page,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("semafor_crawl")

STANDINGS_DIR = ROOT / "data" / "raw" / "semafor" / "standings"
CLUB_LINK_RE = re.compile(r"/klubovi/(\d+)/([a-z0-9-]+)/")
CID_RE = re.compile(r"cid=(\d+)")

# National-tier seed: extracted from the homepage in earlier session.
SEED_CIDS = [
    "100391485",   # SuperSport HNL
    "100413651",   # SuperSport Prva NL
    "100418001",   # SuperSport Druga NL
    "100439118",   # SuperSport HNK (cup)
    "100454960",   # 1.NL juniori
    "100454979",   # 1.NL kadeti
    "100454999",   # 1.NL pioniri
]


def _norm_name(s: str | None) -> str:
    if not s:
        return ""
    s = s.lower()
    for marker in ("š. d. d.", "s. d. d.", "š.d.d.", "s.d.d.", " sdd "):
        s = s.replace(marker, "")
    s = re.sub(r"\b(hrvatski |građanski |gradanski )?nogometni klub\b", "", s)
    s = re.sub(r"\b(hnk|gnk|nk|rnk|fk|znk|mnk|snk)\b", "", s)
    s = re.sub(r"\(\s*[a-zšđčćž]+\s*\)", " ", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def _name_tokens(s: str) -> frozenset[str]:
    return frozenset(t for t in _norm_name(s).split() if len(t) > 1)


def fetch_standings(client: SemaforClient, cid: str) -> str | None:
    """Cached fetch of /natjecanja/{cid}/ - returns HTML or None on 404."""
    cache = STANDINGS_DIR / f"{cid}.html"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    url = f"{BASE_URL}/natjecanja/{cid}/"
    elapsed = time.monotonic() - client._last_request  # noqa: SLF001
    if elapsed < client.throttle_s:
        time.sleep(client.throttle_s - elapsed)
    resp = client._client.get(url, follow_redirects=True)  # noqa: SLF001
    client._last_request = time.monotonic()  # noqa: SLF001
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(resp.text, encoding="utf-8")
    return resp.text


def extract_clubs(html: str) -> dict[int, str]:
    return {int(m.group(1)): m.group(2) for m in CLUB_LINK_RE.finditer(html)}


def extract_cids(html: str) -> set[str]:
    return set(CID_RE.findall(html))


def crawl(client: SemaforClient) -> dict[int, str]:
    """BFS over cids ↔ clubs. Returns the discovered {club_id: slug} map."""
    cid_queue: list[str] = list(SEED_CIDS)
    club_queue: list[int] = []
    seen_cids: set[str] = set()
    seen_clubs: dict[int, str] = {}

    # Seed from already-cached club pages (gives the amateur cids we know).
    cache_dir = ROOT / "data" / "raw" / "semafor"
    cached_club_pages = list(cache_dir.glob("*.html"))
    log.info("preloading cids from %d cached club pages", len(cached_club_pages))
    for p in cached_club_pages:
        if p.parent.name == "standings":
            continue
        try:
            html = p.read_text(encoding="utf-8")
            for cid in extract_cids(html):
                if cid not in seen_cids:
                    cid_queue.append(cid)
        except OSError:
            continue

    rounds = 0
    while cid_queue or club_queue:
        rounds += 1
        # Phase A: drain cid queue → discover clubs
        while cid_queue:
            cid = cid_queue.pop()
            if cid in seen_cids:
                continue
            seen_cids.add(cid)
            html = fetch_standings(client, cid)
            if html is None:
                continue
            new_clubs = extract_clubs(html)
            added = 0
            for cid_club, slug in new_clubs.items():
                if cid_club not in seen_clubs:
                    seen_clubs[cid_club] = slug
                    club_queue.append(cid_club)
                    added += 1
            log.info("cid=%s -> %d clubs (%d new). seen_clubs=%d seen_cids=%d",
                     cid, len(new_clubs), added, len(seen_clubs), len(seen_cids))

        # Phase B: drain club queue → discover further cids
        while club_queue:
            cid_club = club_queue.pop()
            html = client.fetch_html(cid_club)
            if html is None:
                continue
            for cid in extract_cids(html):
                if cid not in seen_cids:
                    cid_queue.append(cid)
            # Break out periodically to refill cid queue (BFS-ish behaviour).
            if cid_queue:
                break

        log.info("round %d complete. queue_cid=%d queue_clubs=%d",
                 rounds, len(cid_queue), len(club_queue))

    log.info("crawl done: %d cids, %d clubs", len(seen_cids), len(seen_clubs))
    return seen_clubs


def match_clubs_to_db(conn, sf: SemaforClient, discovered: dict[int, str]) -> int:
    """For each discovered Semafor club, try to match to a DB club.

    Returns the number of clubs.semafor_url cells filled. Skips ambiguous
    matches and clubs that already have a semafor_url.
    """
    clubs = conn.execute(
        "SELECT id, canonical_name, city, semafor_url FROM clubs"
    ).fetchall()
    by_city: dict[str, list[dict]] = {}
    by_name: dict[str, list[dict]] = {}
    for c in clubs:
        city_key = (c["city"] or "").lower().strip()
        by_city.setdefault(city_key, []).append(dict(c))
        # Also index by name tokens for fallback when city is missing/different
        for tok in _name_tokens(c["canonical_name"]):
            by_name.setdefault(tok, []).append(dict(c))

    matched = 0
    ambiguous = 0
    unmatched = 0
    already = 0

    for sid, slug in discovered.items():
        html = sf.fetch_html(sid)
        if html is None:
            continue
        parsed = parse_club_page(html)
        sf_short = parsed.get("short_name") or ""
        sf_full = parsed.get("full_name") or ""
        sf_city = ""
        if sf_full and "," in sf_full:
            sf_city = sf_full.rsplit(",", 1)[-1].strip().lower()
            # Some pages format "City - SubCity" — take the meaningful end.
            if " - " in sf_city:
                sf_city = sf_city.split(" - ")[-1].strip()

        sf_name_core = sf_full.split(",", 1)[0] if sf_full else sf_short
        sf_tokens = (_name_tokens(sf_name_core) | _name_tokens(sf_short)) \
            - _name_tokens(sf_city)

        # Candidates: clubs in same city, plus name-token hits regardless of
        # city (covers DB city formatted differently).
        candidates: dict[int, dict] = {}
        for c in by_city.get(sf_city, []):
            candidates[c["id"]] = c
        for tok in sf_tokens:
            for c in by_name.get(tok, []):
                candidates[c["id"]] = c

        # Score each: tokens-overlap-weighted, city-equality bonus.
        scored: list[tuple[float, dict]] = []
        for c in candidates.values():
            db_tokens = _name_tokens(c["canonical_name"]) - _name_tokens(sf_city)
            overlap = len(sf_tokens & db_tokens)
            both_empty = not sf_tokens and not db_tokens
            if not overlap and not both_empty:
                continue
            score = overlap * 1.0
            if (c["city"] or "").lower().strip() == sf_city and sf_city:
                score += 0.5
            if sf_tokens and db_tokens and sf_tokens.issubset(db_tokens):
                score += 0.5
            if sf_tokens and db_tokens and db_tokens.issubset(sf_tokens):
                score += 0.5
            if both_empty:
                score = 0.3  # city-only match — weak
            scored.append((score, c))

        if not scored:
            unmatched += 1
            continue

        scored.sort(key=lambda t: t[0], reverse=True)
        top, second = scored[0], (scored[1] if len(scored) > 1 else None)
        # Demand clear winner: top must beat second by >= 0.5 OR be the only one.
        if second is not None and top[0] - second[0] < 0.5:
            ambiguous += 1
            continue
        if top[0] < 0.5:
            unmatched += 1
            continue

        club = top[1]
        if club["semafor_url"]:
            already += 1
            continue
        url = canonical_url(sid, slug)
        conn.execute(
            "UPDATE clubs SET semafor_url = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (url, club["id"]),
        )
        matched += 1

    conn.commit()
    log.info(
        "match: filled=%d already_had=%d ambiguous=%d unmatched=%d (of %d discovered)",
        matched, already, ambiguous, unmatched, len(discovered),
    )
    return matched


def run() -> None:
    with connect() as conn, SemaforClient() as sf:
        discovered = crawl(sf)
        match_clubs_to_db(conn, sf, discovered)


if __name__ == "__main__":
    run()
