"""Download all club logos locally so the web app doesn't depend on remote CDNs.

Two sources:

  1) hrnogomet:   https://images.hrnogomet.hr/team_amblems/small/{id}.png
                  -> for every club with a 'hrnogomet-id' alias
  2) SofaScore:   https://api.sofascore.com/api/v1/team/{id}/image
                  -> for top-tier (1-4) clubs; team IDs are derived from the
                     cached raw/sofascore/{tournament}/{season}_teams.json files
                     and persisted as 'sofascore-id' aliases for future reuse

Output: data/logos/{slug}.png — keyed by club slug so the web app can serve a
single stable URL per club regardless of which source provided the image.

Idempotent: existing non-empty files are skipped. 404s from either source are
logged and the club simply ends up logo-less (the <img onerror> fallback in
the template shows a ⚽ emoji).
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from curl_cffi import requests as cf_requests  # noqa: E402

from src.db import add_alias, connect  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fetch_logos")

LOGO_DIR = ROOT / "data" / "logos"
HRNOGOMET_TMPL = "https://images.hrnogomet.hr/team_amblems/small/{id}.png"
SOFASCORE_TMPL = "https://api.sofascore.com/api/v1/team/{id}/image"
SOFASCORE_RAW = ROOT / "data" / "raw" / "sofascore"


def build_sofascore_name_index() -> dict[str, int]:
    """Scan cached SofaScore teams JSON to map team name -> team id."""
    idx: dict[str, int] = {}
    for path in SOFASCORE_RAW.glob("*/[0-9]*_teams.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for team in data.get("teams", []) or []:
            tid, name = team.get("id"), team.get("name")
            if tid and name and name not in idx:
                idx[name] = tid
    return idx


def is_image_response(content: bytes, content_type: str | None) -> bool:
    if not content or len(content) < 100:
        return False
    if content_type and not content_type.startswith("image/"):
        return False
    # PNG magic number
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    # SofaScore sometimes serves SVG (placeholder) — accept those too
    if b"<svg" in content[:200].lower():
        return True
    return True  # other image types ok


def fetch_hrnogomet(httpx_client: httpx.Client, team_id: str) -> bytes | None:
    url = HRNOGOMET_TMPL.format(id=team_id)
    try:
        r = httpx_client.get(url, timeout=15)
    except httpx.HTTPError as e:
        log.debug("hrnogomet fetch error %s: %s", team_id, e)
        return None
    if r.status_code != 200:
        return None
    if not is_image_response(r.content, r.headers.get("content-type")):
        return None
    return r.content


def fetch_sofascore(team_id: int) -> bytes | None:
    """SofaScore image endpoint goes through Cloudflare — use curl_cffi."""
    url = SOFASCORE_TMPL.format(id=team_id)
    try:
        r = cf_requests.get(
            url, impersonate="chrome124", timeout=15,
            headers={"Referer": "https://www.sofascore.com/"},
        )
    except Exception as e:
        log.debug("sofascore fetch error %s: %s", team_id, e)
        return None
    if r.status_code != 200:
        return None
    if not is_image_response(r.content, r.headers.get("content-type")):
        return None
    return r.content


def run() -> None:
    LOGO_DIR.mkdir(parents=True, exist_ok=True)

    with connect() as conn:
        clubs = conn.execute(
            "SELECT id, slug, canonical_name FROM clubs ORDER BY canonical_name"
        ).fetchall()

        # Group hrnogomet & sofascore IDs by club_id.
        alias_rows = conn.execute(
            "SELECT club_id, source, alias FROM club_aliases "
            "WHERE source IN ('hrnogomet-id', 'sofascore-id')"
        ).fetchall()
        ids_by_club: dict[int, dict[str, str]] = {}
        for r in alias_rows:
            ids_by_club.setdefault(r["club_id"], {})[r["source"]] = r["alias"]

        # Build the SofaScore name->id lookup once.
        sofascore_idx = build_sofascore_name_index()
        log.info("sofascore name index: %d entries", len(sofascore_idx))

        # Persist sofascore-id aliases for any club we can match by name —
        # cheap one-time backfill, useful for future tasks too.
        matched = 0
        for c in clubs:
            cid_aliases = ids_by_club.get(c["id"], {})
            if "sofascore-id" in cid_aliases:
                continue
            sid = sofascore_idx.get(c["canonical_name"])
            if sid:
                add_alias(conn, c["id"], str(sid), "sofascore-id")
                cid_aliases["sofascore-id"] = str(sid)
                ids_by_club[c["id"]] = cid_aliases
                matched += 1
        if matched:
            conn.commit()
            log.info("added %d sofascore-id aliases from raw cache", matched)

        counters = {"skip": 0, "hrnogomet": 0, "sofascore": 0, "miss": 0}
        with httpx.Client(timeout=15) as hx:
            for c in clubs:
                out = LOGO_DIR / f"{c['slug']}.png"
                if out.exists() and out.stat().st_size > 100:
                    counters["skip"] += 1
                    continue

                aliases = ids_by_club.get(c["id"], {})
                hr_id = aliases.get("hrnogomet-id")
                so_id = aliases.get("sofascore-id")

                blob: bytes | None = None
                source: str = "miss"
                if hr_id:
                    blob = fetch_hrnogomet(hx, hr_id)
                    if blob:
                        source = "hrnogomet"
                if not blob and so_id:
                    blob = fetch_sofascore(int(so_id))
                    if blob:
                        source = "sofascore"

                if blob:
                    out.write_bytes(blob)
                    counters[source] += 1
                    log.debug("✓ %s [%s] %d bytes", c["slug"], source, len(blob))
                else:
                    counters["miss"] += 1
                    log.debug("✗ %s (no logo found)", c["slug"])

                # Polite throttle so we don't get rate limited.
                time.sleep(0.05)

        log.info("done. counters=%s", counters)
        log.info("logos on disk: %d", sum(1 for _ in LOGO_DIR.glob("*.png")))


if __name__ == "__main__":
    run()
