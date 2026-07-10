"""Render per-club PWA app icons from the sized crest catalog.

For every slug with a crest at data/logos_sized/256/{slug}.png (preferring the
512 tier as the source when it exists — better quality), render four variants
into data/app_icons/{variant}/{slug}.png:

  - 512          512x512, opaque WHITE background (iOS renders black behind
                 transparent pixels), crest contained centered in a 70% box.
  - 192          192x192, same composition (70% box).
  - maskable-512 512x512 white, crest in a 56% box — safe zone for circular
                 masks (Android adaptive icons crop to a circle of radius 40%
                 of the canvas = 205px; a square crest's half-diagonal at box
                 B is B*sqrt(2)/2, so B <= 205*2/sqrt(2) ~= 290px -> 56%).
  - 180          180x180 white, crest in a 74% box (Apple touch icon; iOS
                 rounds corners itself, a larger crest reads better).

Upscaling the crest source is allowed (LANCZOS) — icons display small, so a
~1.4x upscale of a 256/512px crest is fine. Output is RGB (no alpha), PNG
quantized to 256 colors like the rest of the catalog. Idempotent per mtime:
a variant is re-rendered only when its source is newer than the output.

Run: uv run python scripts/49_render_app_icons.py [--only slug1,slug2]
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SIZED_DIR = ROOT / "data" / "logos_sized"
OUT_DIR = ROOT / "data" / "app_icons"

WHITE = (255, 255, 255)

# variant name -> (canvas size, crest box fraction)
VARIANTS: dict[str, tuple[int, float]] = {
    "512": (512, 0.70),
    "192": (192, 0.70),
    "maskable-512": (512, 0.56),
    "180": (180, 0.74),
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("render_app_icons")


def source_for(slug: str) -> Path | None:
    for tier in ("512", "256"):
        p = SIZED_DIR / tier / f"{slug}.png"
        if p.exists():
            return p
    return None


def save_quantized(img: Image.Image, dst: Path) -> None:
    img.convert("RGB").quantize(colors=256, method=Image.Quantize.FASTOCTREE).save(
        dst, "PNG", optimize=True
    )


def render_variant(crest: Image.Image, canvas_size: int, box_frac: float, dst: Path) -> None:
    box = int(canvas_size * box_frac)
    w, h = crest.size
    scale = min(box / w, box / h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    fitted = crest.resize((nw, nh), Image.LANCZOS)

    canvas = Image.new("RGB", (canvas_size, canvas_size), WHITE)
    pos = ((canvas_size - nw) // 2, (canvas_size - nh) // 2)
    canvas.paste(fitted, pos, mask=fitted)  # alpha channel as mask -> white shows through
    save_quantized(canvas, dst)


def run(only: set[str] | None = None) -> None:
    slugs = sorted(p.stem for p in (SIZED_DIR / "256").glob("*.png"))
    if only:
        slugs = [s for s in slugs if s in only]
    for variant in VARIANTS:
        (OUT_DIR / variant).mkdir(parents=True, exist_ok=True)

    stats = {"rendered": 0, "skipped_fresh": 0, "no_source": 0}
    for slug in slugs:
        src = source_for(slug)
        if not src:
            stats["no_source"] += 1
            continue
        src_mtime = src.stat().st_mtime
        crest = None
        for variant, (canvas_size, box_frac) in VARIANTS.items():
            dst = OUT_DIR / variant / f"{slug}.png"
            if dst.exists() and dst.stat().st_mtime >= src_mtime:
                stats["skipped_fresh"] += 1
                continue
            if crest is None:
                crest = Image.open(src).convert("RGBA")
            render_variant(crest, canvas_size, box_frac, dst)
            stats["rendered"] += 1

    per_variant = {v: sum(1 for _ in (OUT_DIR / v).glob("*.png")) for v in VARIANTS}
    log.info("done. %s variants=%s", stats, per_variant)


if __name__ == "__main__":
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    run(only)
