"""Thin client over the Firecrawl v2 HTTP API.

We talk to the API directly (not via the MCP server) so this can be embedded in
the backfill pipeline and re-used from scripts without external state. Every
response is cached under data/raw/firecrawl/<endpoint>/<hash>.json so repeat
runs don't burn credits.

Endpoints we use:
  POST /v2/search  -> find candidate URLs for a club query
  POST /v2/scrape  -> get clean markdown OR an LLM-extracted JSON object from
                       a single URL, driven by a JSON schema we pass in
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BASE_URL = "https://api.firecrawl.dev/v2"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "firecrawl"


class InsufficientCreditsError(RuntimeError):
    """Raised when the Firecrawl plan has no credits left.

    The bulk backfill loop catches this and exits cleanly instead of looping
    through hundreds of identical 402 errors."""


def _cache_key(endpoint: str, payload: dict) -> Path:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    return RAW_DIR / endpoint / f"{digest}.json"


class FirecrawlClient:
    """Firecrawl HTTP client with automatic rotation across multiple API keys.

    Keys come from (in priority order):
      1. `api_keys` constructor argument (list or single string)
      2. FIRECRAWL_API_KEYS env var, comma-separated
      3. FIRECRAWL_API_KEY env var (backward compat, single key)

    When the active key hits InsufficientCreditsError, we transparently rotate
    to the next one and retry the request. Once every key is exhausted, the
    exception bubbles up so the caller can stop gracefully.
    """

    def __init__(
        self,
        api_keys: str | list[str] | None = None,
        throttle_s: float = 0.5,
    ):
        if api_keys is None:
            multi = os.environ.get("FIRECRAWL_API_KEYS", "").strip()
            if multi:
                api_keys = [k.strip() for k in multi.split(",") if k.strip()]
            elif os.environ.get("FIRECRAWL_API_KEY"):
                api_keys = [os.environ["FIRECRAWL_API_KEY"]]
            else:
                api_keys = []
        if isinstance(api_keys, str):
            api_keys = [api_keys]
        if not api_keys:
            raise RuntimeError("FIRECRAWL_API_KEY(S) not set (env or .env)")
        self.api_keys = list(api_keys)
        self._active_idx = 0
        self.throttle_s = throttle_s
        self._client = httpx.Client(
            headers={
                "Authorization": f"Bearer {self.api_keys[self._active_idx]}",
                "Content-Type": "application/json",
            },
            timeout=90.0,
        )
        self._last_request = 0.0
        self.credits_used = 0

    @property
    def api_key(self) -> str:
        return self.api_keys[self._active_idx]

    def _rotate_key(self) -> bool:
        """Switch to the next configured API key. Returns False if no more."""
        if self._active_idx + 1 >= len(self.api_keys):
            return False
        self._active_idx += 1
        self._client.headers["Authorization"] = f"Bearer {self.api_keys[self._active_idx]}"
        logger.warning(
            "firecrawl rotated to key #%d/%d", self._active_idx + 1, len(self.api_keys)
        )
        return True

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def _post(self, endpoint: str, payload: dict) -> dict[str, Any]:
        cache = _cache_key(endpoint, payload)
        if cache.exists():
            data = json.loads(cache.read_text())
            logger.debug("firecrawl cache hit %s", cache.name)
            return data

        elapsed = time.monotonic() - self._last_request
        if elapsed < self.throttle_s:
            time.sleep(self.throttle_s - elapsed)

        url = f"{BASE_URL}/{endpoint}"
        for attempt in range(4):
            resp = self._client.post(url, json=payload)
            self._last_request = time.monotonic()
            if resp.status_code == 429:
                wait = 2 ** attempt
                logger.warning("firecrawl 429, sleeping %ss", wait)
                time.sleep(wait)
                continue
            is_insufficient = (
                resp.status_code == 402
                or (resp.status_code in (402, 429) and "insufficient" in resp.text.lower())
            )
            if is_insufficient:
                # Try to fail over to the next configured key before giving up.
                if self._rotate_key():
                    continue  # retry same request with new key
                raise InsufficientCreditsError(resp.text[:300])
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"firecrawl {endpoint} {resp.status_code}: {resp.text[:300]}"
                )
            data = resp.json()
            # Track credits via metadata when present.
            credits = (
                (data.get("data") or {}).get("metadata", {}).get("creditsUsed")
                or data.get("data", {}).get("creditsUsed")
                or data.get("creditsUsed")
            )
            if isinstance(credits, int):
                self.credits_used += credits
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            return data
        raise RuntimeError(f"firecrawl rate limit exhausted for {endpoint}")

    def remaining_credits(self) -> int | None:
        """Return remaining credits on the currently active key, or None."""
        try:
            r = self._client.get(f"{BASE_URL}/team/credit-usage")
            if r.status_code == 200:
                return int((r.json().get("data") or {}).get("remainingCredits") or 0)
        except (httpx.HTTPError, ValueError, KeyError):
            return None
        return None

    def credits_across_keys(self) -> list[tuple[str, int | None]]:
        """Check balance on every configured key. Restores the original
        active key afterwards. Useful for startup logging."""
        original = self._active_idx
        out: list[tuple[str, int | None]] = []
        try:
            for i, _key in enumerate(self.api_keys):
                self._active_idx = i
                self._client.headers["Authorization"] = f"Bearer {self.api_keys[i]}"
                out.append((f"key#{i+1}", self.remaining_credits()))
        finally:
            self._active_idx = original
            self._client.headers["Authorization"] = f"Bearer {self.api_keys[original]}"
        return out

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        payload = {"query": query, "limit": limit}
        data = self._post("search", payload)
        return ((data.get("data") or {}).get("web")) or []

    def scrape_json(
        self,
        url: str,
        schema: dict[str, Any],
        prompt: str,
    ) -> dict[str, Any]:
        payload = {
            "url": url,
            "formats": [
                {"type": "json", "prompt": prompt, "schema": schema}
            ],
        }
        data = self._post("scrape", payload)
        return (data.get("data") or {}).get("json") or {}
