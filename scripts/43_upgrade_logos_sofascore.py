"""Second-pass logo upgrade from SofaScore for clubs still below 100px.

Runs after scripts/42_upgrade_logos.py (Semafor originals). SofaScore serves
150x150 team images — a real upgrade for the ~60-70px hrnogomet thumbnails
that had no usable Semafor original.

Placeholder guard: SofaScore returns a generic badge for teams without a real
logo. We fetch everything first, then drop any blob whose hash appears for
more than PLACEHOLDER_THRESHOLD teams before writing.

Same output convention as 42: full-res copy in data/logos_orig/{slug}.png,
quantized web PNG in data/logos/{slug}.png. Only replaces files it can beat
by MIN_UPGRADE_FACTOR in max dimension.

Run: uv run python scripts/43_upgrade_logos_sofascore.py [--dry-run]
"""
from __future__ import annotations

import hashlib
import io
import logging
import sys
import time
from collections import Counter
from pathlib import Path

from curl_cffi import requests as cf_requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("upgrade_logos_ss")

LOGO_DIR = ROOT / "data" / "logos"
ORIG_DIR = ROOT / "data" / "logos_orig"
SOFASCORE_TMPL = "https://api.sofascore.com/api/v1/team/{id}/image"

MIN_UPGRADE_FACTOR = 1.3
MAX_CURRENT_DIM = 100          # only clubs still below this are candidates
PLACEHOLDER_THRESHOLD = 3      # same hash on >N teams -> generic badge
WEB_MAX = 512


def current_max_dim(slug: str) -> int:
    p = LOGO_DIR / f"{slug}.png"
    if not p.exists():
        return 0
    try:
        with Image.open(p) as img:
            return max(img.size)
    except Exception:
        return 0


def fetch(team_id: str) -> bytes | None:
    try:
        r = cf_requests.get(
            SOFASCORE_TMPL.format(id=team_id), impersonate="chrome124",
            timeout=15, headers={"Referer": "https://www.sofascore.com/"},
        )
    except Exception as e:
        log.debug("fetch error %s: %s", team_id, e)
        return None
    if r.status_code != 200 or len(r.content) < 100:
        return None
    return r.content


def write_web_png(img: Image.Image, dst: Path) -> None:
    img = img.convert("RGBA")
    if max(img.size) > WEB_MAX:
        img.thumbnail((WEB_MAX, WEB_MAX), Image.LANCZOS)
    img.quantize(colors=256, method=Image.Quantize.FASTOCTREE).save(
        dst, "PNG", optimize=True
    )


def run(dry_run: bool = False) -> None:
    ORIG_DIR.mkdir(parents=True, exist_ok=True)
    conn = connect()
    rows = conn.execute(
        "SELECT c.slug, a.alias FROM clubs c "
        "JOIN club_aliases a ON a.club_id = c.id AND a.source = 'sofascore-id' "
        "ORDER BY c.slug"
    ).fetchall()

    candidates = [(slug, sid) for slug, sid in rows
                  if 0 < current_max_dim(slug) < MAX_CURRENT_DIM]
    log.info("%d candidates below %dpx", len(candidates), MAX_CURRENT_DIM)

    fetched: list[tuple[str, str, bytes]] = []
    for slug, sid in candidates:
        blob = fetch(sid)
        if blob:
            fetched.append((slug, hashlib.md5(blob).hexdigest(), blob))
        time.sleep(0.1)

    hash_counts = Counter(h for _, h, _ in fetched)
    placeholders = {h for h, n in hash_counts.items() if n > PLACEHOLDER_THRESHOLD}
    if placeholders:
        log.info("placeholder hashes: %s", {h: hash_counts[h] for h in placeholders})

    stats = {"upgraded": 0, "placeholder": 0, "no_gain": 0, "bad_image": 0,
             "fetch_fail": len(candidates) - len(fetched)}
    for slug, h, blob in fetched:
        if h in placeholders:
            stats["placeholder"] += 1
            continue
        try:
            img = Image.open(io.BytesIO(blob))
            img.load()
        except Exception:
            stats["bad_image"] += 1
            continue
        old_dim, new_dim = current_max_dim(slug), max(img.size)
        if new_dim < old_dim * MIN_UPGRADE_FACTOR:
            stats["no_gain"] += 1
            continue
        if dry_run:
            log.info("[dry] %s: %dpx -> %dpx", slug, old_dim, new_dim)
        else:
            ext = (img.format or "png").lower().replace("jpeg", "jpg")
            (ORIG_DIR / f"{slug}.{ext}").write_bytes(blob)
            write_web_png(img, LOGO_DIR / f"{slug}.png")
            log.info("%s: %dpx -> %dpx", slug, old_dim, new_dim)
        stats["upgraded"] += 1

    log.info("done. %s", stats)


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
