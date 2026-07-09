"""Third-pass logo upgrade: Facebook page profile pictures, vision-gated.

For clubs whose logo is still below 100px after scripts 42 (Semafor originals)
and 43 (SofaScore), the unauthenticated Graph redirect

    https://graph.facebook.com/{page}/picture?type=large&width=720&height=720

serves the page's profile picture at up to 720px. Unlike the CDN sources this
is NOT guaranteed to be a crest — pages use team photos, sponsors, stadium
shots — so nothing is written to the catalog automatically:

  fetch (default)  downloads candidates to data/verification/fb_logo_candidates/
                   for a human/vision review pass
  --apply FILE     applies only the slugs listed in FILE (one per line),
                   same output convention as 42/43: original to
                   data/logos_orig/{slug}.{ext}, quantized web PNG to
                   data/logos/{slug}.png

Run: uv run python scripts/44_fetch_fb_logos.py [--apply accepted.txt]
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fb_logos")

LOGO_DIR = ROOT / "data" / "logos"
ORIG_DIR = ROOT / "data" / "logos_orig"
STAGING = ROOT / "data" / "verification" / "fb_logo_candidates"

MAX_CURRENT_DIM = 100
WEB_MAX = 512
GRAPH_TMPL = "https://graph.facebook.com/{page}/picture?type=large&width=720&height=720"


def page_handle(fb_url: str) -> str | None:
    """Extract the Graph-addressable handle (page name or numeric id)."""
    m = re.search(r"facebook\.com/profile\.php\?id=(\d+)", fb_url)
    if m:
        return m.group(1)
    m = re.search(r"facebook\.com/([^/?#]+)", fb_url)
    if not m:
        return None
    handle = m.group(1)
    if handle in {"pages", "people", "groups", "pg"}:
        return None
    return handle


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
    img.quantize(colors=256, method=Image.Quantize.FASTOCTREE).save(
        dst, "PNG", optimize=True
    )


def fetch_candidates() -> None:
    STAGING.mkdir(parents=True, exist_ok=True)
    conn = connect()
    rows = conn.execute(
        "SELECT slug, fb_url FROM clubs WHERE fb_url IS NOT NULL ORDER BY slug"
    ).fetchall()
    todo = [(s, u) for s, u in rows if 0 < current_max_dim(s) < MAX_CURRENT_DIM]
    log.info("%d low-res clubs with fb_url", len(todo))

    stats = {"fetched": 0, "no_handle": 0, "fail": 0, "small": 0}
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        for slug, fb_url in todo:
            handle = page_handle(fb_url)
            if not handle:
                stats["no_handle"] += 1
                continue
            try:
                r = client.get(GRAPH_TMPL.format(page=handle))
                r.raise_for_status()
                img = Image.open(io.BytesIO(r.content))
                img.load()
            except Exception as e:
                log.debug("fail %s: %s", slug, e)
                stats["fail"] += 1
                continue
            if max(img.size) < 200:  # not better than what SofaScore would give
                stats["small"] += 1
                continue
            ext = (img.format or "jpg").lower().replace("jpeg", "jpg")
            (STAGING / f"{slug}.{ext}").write_bytes(r.content)
            stats["fetched"] += 1
            time.sleep(0.2)
    log.info("done. %s (staged in %s)", stats, STAGING)


def apply(accept_file: Path) -> None:
    slugs = [s.strip() for s in accept_file.read_text().splitlines() if s.strip()]
    applied = 0
    for slug in slugs:
        matches = list(STAGING.glob(f"{slug}.*"))
        if not matches:
            log.warning("no staged candidate for %s", slug)
            continue
        src = matches[0]
        img = Image.open(src)
        img.load()
        (ORIG_DIR / src.name).write_bytes(src.read_bytes())
        write_web_png(img, LOGO_DIR / f"{slug}.png")
        applied += 1
        log.info("applied %s (%dpx)", slug, max(img.size))
    log.info("applied %d/%d", applied, len(slugs))


if __name__ == "__main__":
    if "--apply" in sys.argv:
        apply(Path(sys.argv[sys.argv.index("--apply") + 1]))
    else:
        fetch_candidates()
