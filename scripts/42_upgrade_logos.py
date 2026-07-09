"""Upgrade club logos to high resolution from Semafor CDN originals.

The existing catalog (data/logos/, populated by scripts 07 + 34) is mostly
tiny: ~60-100px from images.hrnogomet.hr/team_amblems/small/ and Semafor
_resized/..._100_100_wg_t thumbnails. Both CDNs turned out to hide the full
originals:

  resized:  https://hns.family/files/images_comet/Club/_resized/{id}_{hash}_100_100_wg_t.png
  original: https://hns.family/files/images_comet/Club/{id}_{hash}.png   (often 1000px+)

Same trick works for the hash-sharded path variant (images_comet/{aa}/{b}/...).
The hrnogomet CDN has no larger variant (big/large/etc. all serve the same
placeholder), so Semafor originals are the only deterministic upgrade path.

For every club with a semafor_url and a cached page in data/raw/semafor/:

  1. parse logo_url from the cached page
  2. derive the original URL (strip /_resized/ and the _{W}_{H}_wg_t suffix);
     on 404 retry with alternate extensions, then fall back to _280_280_wg_t
  3. keep the best candidate only if it beats the current local file by
     MIN_UPGRADE_FACTOR in max dimension
  4. archive the full-res original in data/logos_orig/{slug}.{ext} and write
     a web-friendly PNG (max WEB_MAX px, RGBA) to data/logos/{slug}.png

Idempotent: clubs whose logos_orig file already exists are skipped.
Run: uv run python scripts/42_upgrade_logos.py [--dry-run]
"""
from __future__ import annotations

import io
import logging
import re
import sys
import time
from pathlib import Path

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402
from src.semafor import extract_club_id, parse_club_page  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("upgrade_logos")

LOGO_DIR = ROOT / "data" / "logos"
ORIG_DIR = ROOT / "data" / "logos_orig"
CACHE = ROOT / "data" / "raw" / "semafor"

RESIZED_RE = re.compile(r"/_resized/(?P<stem>.+?)_\d+_\d+_wg(?:_t)?\.(?P<ext>png|jpe?g|gif)$", re.I)
MIN_UPGRADE_FACTOR = 1.3   # new max-dim must beat current by 30%
WEB_MAX = 512              # max dimension of the web PNG


def original_candidates(logo_url: str) -> list[str]:
    """Derive candidate original URLs from a _resized thumbnail URL."""
    m = RESIZED_RE.search(logo_url)
    if not m:
        # Some club pages embed the original URL directly (no _resized/).
        return [logo_url]
    prefix = logo_url[: m.start()]
    stem, ext = m.group("stem"), m.group("ext").lower()
    exts = [ext] + [e for e in ("png", "jpg", "gif") if e != ext]
    cands = [f"{prefix}/{stem}.{e}" for e in exts]
    # Last resort: the largest resize the CDN pre-renders.
    cands.append(f"{prefix}/_resized/{stem}_280_280_wg_t.{ext}")
    return cands


def fetch_image(client: httpx.Client, url: str) -> tuple[bytes, Image.Image] | None:
    try:
        r = client.get(url)
    except httpx.HTTPError as e:
        log.debug("fetch error %s: %s", url, e)
        return None
    if r.status_code != 200 or len(r.content) < 100:
        return None
    try:
        img = Image.open(io.BytesIO(r.content))
        img.load()
    except Exception:
        return None
    return r.content, img


def current_max_dim(slug: str) -> int:
    p = LOGO_DIR / f"{slug}.png"
    if not p.exists():
        return 0
    try:
        with Image.open(p) as img:
            return max(img.size)
    except Exception:
        return 0


def write_web_png(img: Image.Image, dst: Path) -> None:
    img = img.convert("RGBA")
    if max(img.size) > WEB_MAX:
        img.thumbnail((WEB_MAX, WEB_MAX), Image.LANCZOS)
    # 256-color palette: ~80% smaller, visually lossless on flat crest art.
    img.quantize(colors=256, method=Image.Quantize.FASTOCTREE).save(
        dst, "PNG", optimize=True
    )


def run(dry_run: bool = False) -> None:
    ORIG_DIR.mkdir(parents=True, exist_ok=True)
    conn = connect()
    rows = conn.execute(
        "SELECT slug, semafor_url FROM clubs WHERE semafor_url IS NOT NULL ORDER BY slug"
    ).fetchall()

    stats = {"upgraded": 0, "no_gain": 0, "no_logo": 0, "no_cache": 0, "fetch_fail": 0, "done": 0}
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        for slug, url in rows:
            if any(ORIG_DIR.glob(f"{slug}.*")):
                stats["done"] += 1
                continue
            page = CACHE / f"{extract_club_id(url)}.html"
            if not page.exists():
                stats["no_cache"] += 1
                continue
            logo_url = parse_club_page(page.read_text(errors="ignore")).get("logo_url")
            if not logo_url:
                stats["no_logo"] += 1
                continue

            got = None
            for cand in original_candidates(logo_url):
                got = fetch_image(client, cand)
                if got:
                    break
                time.sleep(0.05)
            if not got:
                stats["fetch_fail"] += 1
                log.warning("no fetchable original for %s (%s)", slug, logo_url)
                continue

            blob, img = got
            old_dim, new_dim = current_max_dim(slug), max(img.size)
            if new_dim < old_dim * MIN_UPGRADE_FACTOR:
                stats["no_gain"] += 1
                log.debug("%s: %dpx -> %dpx, keeping current", slug, old_dim, new_dim)
                continue

            if dry_run:
                log.info("[dry] %s: %dpx -> %dpx", slug, old_dim, new_dim)
            else:
                ext = (img.format or "png").lower().replace("jpeg", "jpg")
                (ORIG_DIR / f"{slug}.{ext}").write_bytes(blob)
                write_web_png(img, LOGO_DIR / f"{slug}.png")
                log.info("%s: %dpx -> %dpx", slug, old_dim, new_dim)
            stats["upgraded"] += 1
            time.sleep(0.05)

    log.info("done. %s", stats)


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
