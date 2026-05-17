"""Client + parser for semafor.hns.family club pages.

Semafor is HNS's official per-club registration directory. Pages are static
HTML behind a generic Cloudflare front (no TLS challenge for HTML), so a
plain httpx call with a browser UA is enough.

Per-page fields we extract from `.clubHeader`:

  short_name        h1 inside .basic_info .title
  full_name         h2 inside .basic_info .title (full registered name + city)
  founded_date      .info li.foundation_date h3        DD.MM.YYYY.
  address           .info li.address h3
  stadium_name      .info li.stadium h3
  phone             .info li.phone h3 a (tel: href preferred)
  lat / lng         #club_map[data-coordinates-x / -y] (only top tiers)
  logo_url          .basic_info .logo img[src]

Address often contains the city; on amateur pages it may BE the city only.
Phone for top tiers is already in +385 international form; for amateur tiers
it can be local (e.g. "032 433-217") — leave normalization to src.phones.

Responses cached under data/raw/semafor/<id>.html so repeat runs are free.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://semafor.hns.family"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "semafor"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "hr,en;q=0.9",
}

_ID_RE = re.compile(r"/(?:en/)?(?:klubovi|clubs)/(\d+)/")
_FOUNDED_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


def extract_club_id(url: str) -> int | None:
    """Return the Semafor numeric club id from a /klubovi/{id}/ URL."""
    m = _ID_RE.search(url)
    return int(m.group(1)) if m else None


def canonical_url(club_id: int, slug: str | None = None) -> str:
    """Build the canonical Semafor URL. Slug is cosmetic — Semafor 301s if missing."""
    tail = f"{slug}/" if slug else ""
    return f"{BASE_URL}/klubovi/{club_id}/{tail}"


class SemaforClient:
    def __init__(self, cache_dir: Path = RAW_DIR, throttle_s: float = 0.4):
        self.cache_dir = cache_dir
        self.throttle_s = throttle_s
        self._client = httpx.Client(headers=HEADERS, timeout=20.0, follow_redirects=True)
        self._last_request = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def _cache_path(self, club_id: int) -> Path:
        return self.cache_dir / f"{club_id}.html"

    def fetch_html(self, url_or_id: str | int, *, refresh: bool = False) -> str | None:
        """Return the page HTML, cached by club id. None on 404."""
        if isinstance(url_or_id, int):
            club_id = url_or_id
            url = canonical_url(club_id)
        else:
            club_id = extract_club_id(url_or_id)
            if club_id is None:
                raise ValueError(f"Cannot extract Semafor id from {url_or_id!r}")
            url = url_or_id

        cache = self._cache_path(club_id)
        if cache.exists() and not refresh:
            return cache.read_text(encoding="utf-8")

        elapsed = time.monotonic() - self._last_request
        if elapsed < self.throttle_s:
            time.sleep(self.throttle_s - elapsed)

        resp = self._client.get(url)
        self._last_request = time.monotonic()
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(resp.text, encoding="utf-8")
        return resp.text

    def fetch_parsed(self, url_or_id: str | int, *, refresh: bool = False) -> dict[str, Any] | None:
        html = self.fetch_html(url_or_id, refresh=refresh)
        if html is None:
            return None
        return parse_club_page(html)


def _text(node) -> str | None:
    if node is None:
        return None
    txt = node.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", txt) or None


def parse_club_page(html: str) -> dict[str, Any]:
    """Parse a Semafor club HTML page into a flat dict.

    Missing fields are returned as None. Only the keys listed in the module
    docstring are produced — never invents data.
    """
    soup = BeautifulSoup(html, "html.parser")

    out: dict[str, Any] = {
        "short_name": None,
        "full_name": None,
        "founded_date": None,
        "founded_year": None,
        "address": None,
        "stadium_name": None,
        "phone": None,
        "lat": None,
        "lng": None,
        "logo_url": None,
    }

    header = soup.select_one(".clubHeader")
    if header is None:
        return out

    title = header.select_one(".basic_info .title")
    if title:
        out["short_name"] = _text(title.select_one("h1"))
        out["full_name"] = _text(title.select_one("h2"))

    logo_img = header.select_one(".basic_info .logo img[src]")
    if logo_img:
        out["logo_url"] = logo_img.get("src")

    for li in header.select(".info ul > li"):
        classes = li.get("class") or []
        value = _text(li.select_one("h3"))
        if value is None:
            continue
        if "foundation_date" in classes:
            out["founded_date"] = value
            m = _FOUNDED_RE.search(value)
            if m:
                out["founded_year"] = int(m.group(3))
        elif "address" in classes:
            out["address"] = value
        elif "stadium" in classes:
            out["stadium_name"] = value
        elif "phone" in classes:
            # tel: href is the cleanest form when present
            a = li.select_one("h3 a[href^='tel:']")
            if a:
                out["phone"] = a["href"][4:].strip() or value
            else:
                out["phone"] = value

    map_div = header.select_one("#club_map[data-coordinates-x]")
    if map_div:
        try:
            out["lat"] = float(str(map_div.get("data-coordinates-x")).strip())
            out["lng"] = float(str(map_div.get("data-coordinates-y")).strip())
        except (TypeError, ValueError):
            pass

    return out


def city_from_address(address: str | None) -> str | None:
    """Best-effort city extraction from a Semafor address string.

    Patterns seen:
      'Brdovec'                                          -> 'Brdovec'
      'Trg X 1, Grubišno Polje'                          -> 'Grubišno Polje'
      'Maksimirska 128, 10000 Zagreb'                    -> 'Zagreb'
      'Vukovar, Rudolfa Perešina 08., 32000 Vukovar'     -> 'Vukovar'
    """
    if not address:
        return None
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if not parts:
        return None
    # The trailing component usually carries the city — sometimes prefixed
    # by a 5-digit ZIP we can strip.
    last = parts[-1]
    last = re.sub(r"^\d{4,5}\s+", "", last)
    return last or None
