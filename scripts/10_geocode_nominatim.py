"""Geocode the remaining clubs via Nominatim (OpenStreetMap).

Per-row query is built from the richest piece of location info we have:

  1. `address` (when Firecrawl populated it)
  2. `city + county` (when SofaScore or hrnogomet did)
  3. `derived place from canonical_name + county` (fallback for amateur clubs
     where the place is usually embedded in the club name, e.g. "NK Kloštar
     Ivanić" -> "Kloštar Ivanić")

Rate limit: 1 req/sec per Nominatim usage policy. Responses are cached under
data/raw/nominatim/ keyed by SHA of the query so reruns don't re-hit the
service. Set NOMINATIM_LIMIT env var to a small number for quick smoke tests.

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


def build_query(club: dict) -> str | None:
    """Return the best Nominatim query string for this club, or None."""
    if club.get("address"):
        return f"{club['address']}, Hrvatska"
    county = (club.get("county") or "").replace(" županija", "").strip()
    if club.get("city"):
        bits = [club["city"]]
        if county:
            bits.append(county)
        return ", ".join(bits) + ", Hrvatska"
    # Last resort: parse a place out of the canonical name.
    place = _strip_prefix(club["canonical_name"] or "")
    # Very short / single-character names won't geocode well — skip.
    if len(place) < 3:
        return None
    bits = [place]
    if county:
        bits.append(county)
    return ", ".join(bits) + ", Hrvatska"


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
        with httpx.Client(timeout=20) as hx:
            for i, r in enumerate(rows, 1):
                row = dict(r)
                q = build_query(row)
                if not q:
                    counters["no_query"] += 1
                    continue
                hit = geocode(hx, q)
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
                        "progress %d/%d  ok=%d no_query=%d no_hit=%d",
                        i, len(rows), counters["ok"], counters["no_query"],
                        counters["no_hit"],
                    )
            conn.commit()
            log.info("done. counters=%s", counters)
            total = conn.execute(
                "SELECT COUNT(*) FROM clubs WHERE lat IS NOT NULL"
            ).fetchone()[0]
            log.info("clubs with coords now: %d", total)


if __name__ == "__main__":
    run()
