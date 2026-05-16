from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from curl_cffi import requests as curl_requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.sofascore.com/api/v1"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "sofascore"

# SofaScore requires a real-browser TLS fingerprint (Cloudflare JA3 check).
# curl_cffi.impersonate handles this; plain httpx/requests returns 403.
IMPERSONATE = "chrome124"


class SofaScoreClient:
    def __init__(self, cache_dir: Path = RAW_DIR, throttle_s: float = 1.0):
        self.cache_dir = cache_dir
        self.throttle_s = throttle_s
        self._session = curl_requests.Session(impersonate=IMPERSONATE)
        self._session.headers.update({"Referer": "https://www.sofascore.com/"})
        self._last_request = 0.0

    def close(self) -> None:
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def _get(self, path: str, cache_key: Path | None = None) -> dict[str, Any]:
        if cache_key and cache_key.exists():
            logger.debug("cache hit: %s", cache_key)
            return json.loads(cache_key.read_text())

        elapsed = time.monotonic() - self._last_request
        if elapsed < self.throttle_s:
            time.sleep(self.throttle_s - elapsed)

        url = f"{BASE_URL}{path}"
        for attempt in range(5):
            resp = self._session.get(url, timeout=20)
            self._last_request = time.monotonic()
            if resp.status_code == 429:
                wait = 2 ** attempt
                logger.warning("429 from sofascore, sleeping %ss", wait)
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"sofascore {resp.status_code} on {path}: {resp.text[:200]}"
                )
            data = resp.json()
            if cache_key:
                cache_key.parent.mkdir(parents=True, exist_ok=True)
                cache_key.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            return data
        raise RuntimeError(f"sofascore rate limit exhausted for {path}")

    def seasons(self, tournament_id: int) -> list[dict[str, Any]]:
        cache = self.cache_dir / str(tournament_id) / "_seasons.json"
        data = self._get(f"/unique-tournament/{tournament_id}/seasons", cache_key=cache)
        return data.get("seasons", [])

    def current_season(self, tournament_id: int) -> dict[str, Any] | None:
        seasons = self.seasons(tournament_id)
        return seasons[0] if seasons else None

    def teams(self, tournament_id: int, season_id: int) -> list[dict[str, Any]]:
        cache = self.cache_dir / str(tournament_id) / f"{season_id}_teams.json"
        data = self._get(
            f"/unique-tournament/{tournament_id}/season/{season_id}/teams",
            cache_key=cache,
        )
        return data.get("teams", [])

    def team(self, team_id: int) -> dict[str, Any]:
        cache = self.cache_dir / "teams" / f"{team_id}.json"
        data = self._get(f"/team/{team_id}", cache_key=cache)
        return data.get("team", data)
