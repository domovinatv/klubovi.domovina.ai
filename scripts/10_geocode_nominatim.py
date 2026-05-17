"""Geocode the remaining clubs via Nominatim (OpenStreetMap).

For each club we generate an ORDERED list of candidate queries from most
specific to most general, and try them until one returns a hit:

  1. `<address>, Hrvatska`                       (Firecrawl-extracted street)
  2. `<address tail>, Hrvatska`                  (last 2 comma-chunks; useful
                                                  when street numbers confuse
                                                  Nominatim but the village
                                                  alone resolves)
  3. `<city>, <county>, Hrvatska`                (disambiguates duplicate
                                                  city names like Blato)
  4. `<city>, Hrvatska`                          (unique city wins)
  5. `<place from name>, <county>, Hrvatska`     ("NK Kloštar Ivanić" -> village)
  6. `<place from name>, Hrvatska`               (last resort)

Rate limit: 1 req/sec per Nominatim usage policy. Responses are cached
under data/raw/nominatim/ keyed by SHA of the query so reruns don't re-hit
the service - and clubs that share a city query "pay" only once.

Idempotent: skips rows that already have lat/lng.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("geocode")

CACHE_DIR = ROOT / "data" / "raw" / "nominatim"
USER_AGENT = "hrnk-baza/0.1 (local research; one-shot bulk geocode of HR football clubs)"
ENDPOINT = "https://nominatim.openstreetmap.org/search"

_PREFIX_RE = re.compile(r"^(HNK|GNK|NK|RNK|MNK|HAŠK|ŠNK|GŠNK|BŠK)\s+", re.IGNORECASE)
_PAREN_RE = re.compile(r"\s*\([^)]+\)\s*$")


def _strip_prefix(name: str) -> str:
    n = _PREFIX_RE.sub("", name).strip()
    n = _PAREN_RE.sub("", n).strip()
    return n


def _addr_tail(addr: str) -> str | None:
    """Drop street/number prefix; keep last 2 comma-separated chunks.

    "Ulica 32 br. 192, Blato, Otok Korčula, Hrvatska" -> "Otok Korčula, Hrvatska"
    is too coarse; we want "Blato, Otok Korčula" — the locality + region.
    """
    parts = [p.strip() for p in addr.split(",") if p.strip()]
    # Strip trailing "Hrvatska" if the source already added it.
    if parts and parts[-1].lower() == "hrvatska":
        parts = parts[:-1]
    if len(parts) >= 3:
        return ", ".join(parts[-2:])
    return None


def build_query_candidates(club: dict) -> list[str]:
    """Ordered query candidates from most specific to most general."""
    out: list[str] = []
    county = (club.get("county") or "").replace(" županija", "").strip()
    address = (club.get("address") or "").strip()
    city = (club.get("city") or "").strip()
    name_place = _strip_prefix(club.get("canonical_name") or "")
    if len(name_place) < 3:
        name_place = ""

    if address:
        out.append(f"{address}, Hrvatska")
        tail = _addr_tail(address)
        if tail:
            out.append(f"{tail}, Hrvatska")
    if city and county:
        out.append(f"{city}, {county}, Hrvatska")
    if city:
        out.append(f"{city}, Hrvatska")
    if name_place and county:
        out.append(f"{name_place}, {county}, Hrvatska")
    if name_place:
        out.append(f"{name_place}, Hrvatska")

    # Dedupe preserving order.
    seen: set[str] = set()
    return [q for q in out if not (q in seen or seen.add(q))]


def cache_path(query: str) -> Path:
    h = hashlib.sha256(query.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{h}.json"


def geocode(client: httpx.Client, query: str) -> tuple[float, float] | None:
    cache = cache_path(query)
    if cache.exists():
        data = json.loads(cache.read_text())
    else:
        # Polite delay just before each network call.
        time.sleep(1.05)
        try:
            r = client.get(
                ENDPOINT,
                params={
                    "q": query,
                    "format": "json",
                    "countrycodes": "hr",
                    "limit": 1,
                },
                headers={"User-Agent": USER_AGENT},
                timeout=15,
            )
        except httpx.HTTPError as e:
            log.warning("network error for %r: %s", query, e)
            return None
        if r.status_code != 200:
            log.warning("nominatim %d for %r", r.status_code, query)
            return None
        data = r.json()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, ensure_ascii=False))

    if not data:
        return None
    first = data[0]
    try:
        return float(first["lat"]), float(first["lon"])
    except (KeyError, TypeError, ValueError):
        return None


def run() -> None:
    limit_env = os.environ.get("NOMINATIM_LIMIT")
    limit = int(limit_env) if limit_env and limit_env.isdigit() else None

    with connect() as conn:
        rows = conn.execute(
            "SELECT id, slug, canonical_name, city, county, address "
            "FROM clubs WHERE lat IS NULL"
        ).fetchall()
        if limit:
            rows = rows[:limit]
        log.info("to geocode: %d clubs", len(rows))

        counters = {"ok": 0, "no_query": 0, "no_hit": 0}
        # Track which candidate position got the hit — useful to see whether
        # the fallback levels are paying off.
        hit_by_level: dict[int, int] = {}
        with httpx.Client(timeout=20) as hx:
            for i, r in enumerate(rows, 1):
                row = dict(r)
                candidates = build_query_candidates(row)
                if not candidates:
                    counters["no_query"] += 1
                    continue

                hit: tuple[float, float] | None = None
                for level, q in enumerate(candidates, 1):
                    hit = geocode(hx, q)
                    if hit:
                        hit_by_level[level] = hit_by_level.get(level, 0) + 1
                        break

                if not hit:
                    counters["no_hit"] += 1
                else:
                    lat, lng = hit
                    conn.execute(
                        "UPDATE clubs SET lat = ?, lng = ? WHERE id = ?",
                        (lat, lng, row["id"]),
                    )
                    counters["ok"] += 1

                if i % 25 == 0:
                    conn.commit()
                    log.info(
                        "progress %d/%d  ok=%d no_query=%d no_hit=%d  hits-per-level=%s",
                        i, len(rows), counters["ok"], counters["no_query"],
                        counters["no_hit"], hit_by_level,
                    )
            conn.commit()
            log.info("done. counters=%s  hits-per-level=%s", counters, hit_by_level)
            total = conn.execute(
                "SELECT COUNT(*) FROM clubs WHERE lat IS NOT NULL"
            ).fetchone()[0]
            log.info("clubs with coords now: %d", total)


if __name__ == "__main__":
    run()
