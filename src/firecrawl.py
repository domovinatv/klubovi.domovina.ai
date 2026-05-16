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


def _cache_key(endpoint: str, payload: dict) -> Path:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    return RAW_DIR / endpoint / f"{digest}.json"


class FirecrawlClient:
    def __init__(self, api_key: str | None = None, throttle_s: float = 0.5):
        self.api_key = api_key or os.environ.get("FIRECRAWL_API_KEY")
        if not self.api_key:
            raise RuntimeError("FIRECRAWL_API_KEY not set (env or .env)")
        self.throttle_s = throttle_s
        self._client = httpx.Client(
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=90.0,
        )
        self._last_request = 0.0
        self.credits_used = 0

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
