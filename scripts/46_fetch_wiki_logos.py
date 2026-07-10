"""Wikipedia/Commons logo sweep for clubs whose catalog logo is still small.

Top-tier crests turned out to live on Wikipedia as SVGs (rendered by Wikimedia
at any width via Special:FilePath) or decent fair-use PNGs. This sweep asks
en+hr Wikipedia's pageimages API for every club below MAX_CURRENT_DIM, trying
title candidates derived from the canonical name (disambiguator stripped,
city-suffixed variants).

Like the Facebook pass (44), results are NOT trusted blindly — a title hit can
be a namesake club from another country or return a stadium photo. Candidates
are staged with a manifest for a vision/identity review:

  fetch (default)   stage images to data/verification/wiki_logo_candidates/
                    and write manifest.tsv (slug, matched title, wiki, size)
  --apply FILE      apply accepted slugs (one per line): original to
                    data/logos_orig/, quantized web PNG to data/logos/

Run: uv run python scripts/46_fetch_wiki_logos.py [--apply accepted.txt]
"""
from __future__ import annotations

import io
import logging
import re
import sys
import time
import urllib.parse
from pathlib import Path

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wiki_logos")

LOGO_DIR = ROOT / "data" / "logos"
ORIG_DIR = ROOT / "data" / "logos_orig"
STAGING = ROOT / "data" / "verification" / "wiki_logo_candidates"

MAX_CURRENT_DIM = 256
MIN_UPGRADE_FACTOR = 1.3
SVG_RENDER_WIDTH = 1024
WEB_MAX = 512
UA = {"User-Agent": "klubovi.domovina.ai logo backfill (stepanic.matija@gmail.com)"}

_PAREN_RE = re.compile(r"\s*\([^)]*\)")


def title_candidates(canonical: str, city: str | None) -> list[str]:
    base = _PAREN_RE.sub("", canonical).strip()
    cands = [base]
    if city:
        city = city.strip()
        if city and city.lower() not in base.lower():
            cands.append(f"{base} {city}")
    if canonical not in cands:
        cands.append(canonical)
    return cands


def page_image(client: httpx.Client, wiki: str, title: str) -> tuple[str, str] | None:
    """Return (resolved_title, original_image_url) or None."""
    try:
        r = client.get(
            f"https://{wiki}.wikipedia.org/w/api.php",
            params={
                "action": "query", "titles": title, "prop": "pageimages",
                "piprop": "original", "format": "json", "redirects": 1,
            },
        )
        pages = r.json()["query"]["pages"]
    except Exception:
        return None
    for p in pages.values():
        src = p.get("original", {}).get("source")
        if src:
            return p.get("title", title), src
    return None


def fetch_image(client: httpx.Client, url: str) -> tuple[bytes, Image.Image] | None:
    if url.lower().endswith(".svg"):
        fname = url.rsplit("/", 1)[-1]
        url = (
            "https://commons.wikimedia.org/wiki/Special:FilePath/"
            f"{urllib.parse.quote(fname)}?width={SVG_RENDER_WIDTH}"
        )
    try:
        r = client.get(url)
        if r.status_code != 200 or len(r.content) < 100:
            return None
        img = Image.open(io.BytesIO(r.content))
        img.load()
        return r.content, img
    except Exception:
        return None


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
        "SELECT slug, canonical_name, city FROM clubs ORDER BY slug"
    ).fetchall()
    todo = [r for r in rows if 0 < current_max_dim(r["slug"]) < MAX_CURRENT_DIM]
    log.info("%d clubs below %dpx", len(todo), MAX_CURRENT_DIM)

    manifest = STAGING / "manifest.tsv"
    lines = []
    stats = {"staged": 0, "no_article": 0, "no_gain": 0, "fetch_fail": 0}
    with httpx.Client(timeout=25, follow_redirects=True, headers=UA) as client:
        for r in todo:
            hit = None
            for wiki in ("hr", "en"):
                for title in title_candidates(r["canonical_name"], r["city"]):
                    hit = page_image(client, wiki, title)
                    if hit:
                        break
                    time.sleep(0.05)
                if hit:
                    break
            if not hit:
                stats["no_article"] += 1
                continue
            resolved, img_url = hit
            got = fetch_image(client, img_url)
            if not got:
                stats["fetch_fail"] += 1
                continue
            blob, img = got
            if max(img.size) < current_max_dim(r["slug"]) * MIN_UPGRADE_FACTOR:
                stats["no_gain"] += 1
                continue
            ext = (img.format or "png").lower().replace("jpeg", "jpg")
            (STAGING / f"{r['slug']}.{ext}").write_bytes(blob)
            lines.append(
                f"{r['slug']}\t{wiki}:{resolved}\t{img_url}\t{img.size[0]}x{img.size[1]}"
            )
            stats["staged"] += 1
            log.info("staged %s <- %s:%s (%dx%d)", r["slug"], wiki, resolved, *img.size)
    manifest.write_text("\n".join(lines) + "\n" if lines else "")
    log.info("done. %s (staging: %s)", stats, STAGING)


def apply(accept_file: Path) -> None:
    slugs = [s.strip() for s in accept_file.read_text().splitlines() if s.strip()]
    applied = 0
    for slug in slugs:
        matches = [p for p in STAGING.glob(f"{slug}.*") if p.suffix != ".tsv"]
        if not matches:
            log.warning("no staged candidate for %s", slug)
            continue
        src = matches[0]
        img = Image.open(src)
        img.load()
        for old in ORIG_DIR.glob(f"{slug}.*"):
            old.unlink()
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
