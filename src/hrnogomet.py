"""Client for the api.prod.hrnogomet.hr backend (Flutter web app HRnogomet).

Authentication: API requires the static `x-hrnogomet-uuid` header (extracted
verbatim from the Flutter bundle) and tolerates any Bearer token shape, so we
send a sentinel "Bearer x". Endpoints requiring a real JWT (e.g. /leagues,
/teams?id=...) are out of scope; we rely on:

  GET /county/leagues
  GET /team-standings?shortname=<league_shortname>
  GET /teams/<team_id>
  GET /season/<season_id>

All responses are cached under data/raw/hrnogomet/ for reproducibility.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.prod.hrnogomet.hr"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "hrnogomet"

HEADERS = {
    "x-hrnogomet-uuid": "8147731f-bf23-4f6e-9484-75b9b55c9a9a",
    "Authorization": "Bearer x",
    "Origin": "https://www.hrnogomet.hr",
    "Referer": "https://www.hrnogomet.hr/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


class HRNogometClient:
    def __init__(self, cache_dir: Path = RAW_DIR, throttle_s: float = 0.3):
        self.cache_dir = cache_dir
        self.throttle_s = throttle_s
        self._client = httpx.Client(headers=HEADERS, timeout=20.0)
        self._last_request = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def _get(self, path: str, cache_key: Path | None = None) -> Any:
        if cache_key and cache_key.exists():
            return json.loads(cache_key.read_text())

        elapsed = time.monotonic() - self._last_request
        if elapsed < self.throttle_s:
            time.sleep(self.throttle_s - elapsed)

        url = f"{BASE_URL}{path}"
        for attempt in range(4):
            resp = self._client.get(url)
            self._last_request = time.monotonic()
            if resp.status_code == 429:
                wait = 2 ** attempt
                logger.warning("429 from hrnogomet, sleeping %ss", wait)
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"hrnogomet {resp.status_code} on {path}: {resp.text[:200]}"
                )
            data = resp.json()
            if cache_key:
                cache_key.parent.mkdir(parents=True, exist_ok=True)
                cache_key.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            return data
        raise RuntimeError(f"hrnogomet rate limit exhausted for {path}")

    def county_leagues(self) -> list[dict[str, Any]]:
        return self._get("/county/leagues", cache_key=self.cache_dir / "county_leagues.json")

    def team_standings(self, shortname: str) -> dict[str, Any]:
        safe = shortname.replace("/", "_").replace(" ", "_")
        cache = self.cache_dir / "standings" / f"{safe}.json"
        return self._get(f"/team-standings?shortname={shortname}", cache_key=cache)

    def team(self, team_id: int) -> dict[str, Any]:
        cache = self.cache_dir / "teams" / f"{team_id}.json"
        return self._get(f"/teams/{team_id}", cache_key=cache)


def build_county_map(payload: list[dict[str, Any]]) -> dict[int, str]:
    """Map countyId -> county name, restricted to ACTUAL Croatian counties.

    Entities in /county/leagues include national tiers ("3. Nogometna Liga",
    "4. Nogometna Liga", etc.) which we must NOT write into clubs.county.
    Real counties have priority=50 and either contain "županija" or equal
    "Grad Zagreb".
    """
    return {
        c["id"]: c["name"]
        for c in payload
        if c.get("priority") == 50
        and ("županija" in c["name"].lower() or c["name"] == "Grad Zagreb")
    }


def county_map_from_cache(cache_dir: Path = RAW_DIR) -> dict[int, str]:
    """Offline county map. Used by the backfill guard, which must be able to
    resolve a club's county without spending a network call mid-run."""
    path = cache_dir / "county_leagues.json"
    if not path.exists():
        return {}
    return build_county_map(json.loads(path.read_text()))


def team_county_from_cache(team_id: int, cache_dir: Path = RAW_DIR) -> str | None:
    """County name for a hrnogomet team id, purely from cached payloads.

    The feed's `teamName` carries a disambiguator but no place ("NK Mladost
    (Z)"), so `countyId` is the only location signal available at backfill
    time for the 31 clubs whose `county` column is empty.
    """
    team_path = cache_dir / "teams" / f"{team_id}.json"
    if not team_path.exists():
        return None
    county_id = json.loads(team_path.read_text()).get("countyId")
    if county_id is None:
        return None
    return county_map_from_cache(cache_dir).get(county_id)
