"""Render the standardized logo size ladder from the single source of truth.

Sources (best first): data/logos_orig/{slug}.svg (vector), then
{slug}.{png,jpg,gif} (raster original), then data/logos/{slug}.png (web copy,
for clubs whose only asset is the legacy catalog file).

Output: data/logos_sized/{size}/{slug}.png for size in SIZES, where the mark
is fit inside a size×size box (aspect preserved, no padding). Tiers are only
rendered when the source honestly fills them:

  - SVG sources render every tier (vectors have no native resolution)
  - raster sources render tiers <= max(source dims); NO upscaling — a 150px
    crest simply has no 192 tier and consumers fall back to the largest
    available (or the legacy /logos/{slug}.png default)

PNGs are 256-color quantized like the rest of the catalog. Idempotent per
mtime: a tier is re-rendered when the source is newer than the output.

Run: uv run python scripts/47_render_logo_sizes.py [--only slug1,slug2]
"""
from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
LOGO_DIR = ROOT / "data" / "logos"
ORIG_DIR = ROOT / "data" / "logos_orig"
SIZED_DIR = ROOT / "data" / "logos_sized"

SIZES = [192, 256, 512, 1024]
RASTER_EXTS = (".png", ".jpg", ".jpeg", ".gif")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("render_sizes")


def source_for(slug: str) -> Path | None:
    svg = ORIG_DIR / f"{slug}.svg"
    if svg.exists():
        return svg
    for ext in RASTER_EXTS:
        p = ORIG_DIR / f"{slug}{ext}"
        if p.exists():
            return p
    legacy = LOGO_DIR / f"{slug}.png"
    return legacy if legacy.exists() else None


def save_quantized(img: Image.Image, dst: Path) -> None:
    img.convert("RGBA").quantize(colors=256, method=Image.Quantize.FASTOCTREE).save(
        dst, "PNG", optimize=True
    )


def render_svg(src: Path, size: int, dst: Path) -> bool:
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        try:
            subprocess.run(
                ["rsvg-convert", "-w", str(size), "-h", str(size),
                 "--keep-aspect-ratio", str(src), "-o", tmp.name],
                check=True, capture_output=True,
            )
            img = Image.open(tmp.name)
            img.load()
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
            log.warning("svg render failed %s@%d: %s", src.name, size, e)
            return False
    save_quantized(img, dst)
    return True


def render_raster(img: Image.Image, size: int, dst: Path) -> None:
    out = img.convert("RGBA")
    out.thumbnail((size, size), Image.LANCZOS)
    save_quantized(out, dst)


def run(only: set[str] | None = None) -> None:
    slugs = sorted(p.stem for p in LOGO_DIR.glob("*.png"))
    if only:
        slugs = [s for s in slugs if s in only]
    for size in SIZES:
        (SIZED_DIR / str(size)).mkdir(parents=True, exist_ok=True)

    stats = {"rendered": 0, "skipped_fresh": 0, "no_source": 0}
    for slug in slugs:
        src = source_for(slug)
        if not src:
            stats["no_source"] += 1
            continue
        is_svg = src.suffix == ".svg"
        img = None
        if not is_svg:
            img = Image.open(src)
            img.load()
        max_dim = None if is_svg else max(img.size)
        for size in SIZES:
            if not is_svg and max_dim < size:
                continue
            dst = SIZED_DIR / str(size) / f"{slug}.png"
            if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
                stats["skipped_fresh"] += 1
                continue
            ok = render_svg(src, size, dst) if is_svg else True
            if not is_svg:
                render_raster(img, size, dst)
            if ok:
                stats["rendered"] += 1

    per_size = {s: sum(1 for _ in (SIZED_DIR / str(s)).glob("*.png")) for s in SIZES}
    log.info("done. %s tiers=%s", stats, per_size)


if __name__ == "__main__":
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    run(only)
