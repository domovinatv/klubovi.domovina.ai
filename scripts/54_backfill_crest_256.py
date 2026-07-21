"""Backfill the 256 (and 192) crest tiers for clubs script 47 left tier-less.

Script 47 renders the logo size ladder but forbids upscaling: a club whose
best raster source is smaller than 256px gets NO 256 tier (and often no 192
tier) at all. That left ~379 of the 1014 catalog clubs without a
data/logos_sized/256/{slug}.png, so script 48 exports them with crest:false
and the wallet app falls back to a generic ball + neutral palette.

This script is the deliberate EXCEPTION to 47's no-upscale rule: for every
club slug in frontend/public/data/clubs.json that has no 256 tier, it renders
one WITH upscaling allowed (LANCZOS, same precedent as script 50's square
icons), and likewise fills a missing 192 tier so the ladder stays consistent.
Justification: the consuming wallet app displays crests at <= ~90 px, so a
LANCZOS-upscaled 256 master from a 150px source is visually fine — far better
than no crest at all. Files written here are upscaled backfills; if a larger
original ever lands in data/logos_orig/, re-running script 47 (which keys off
source mtime) will overwrite them with an honest render.

Source cascade is identical to script 47's source_for(): logos_orig/{slug}.svg
(vector), then logos_orig/{slug}.{png,jpg,jpeg,gif} (raster original), then
the legacy data/logos/{slug}.png web copy.

Render/save pattern matches 47: fit inside size x size (aspect preserved, no
padding), RGBA, 256-color FASTOCTREE quantized PNG.

Idempotent: a tier is only written when the output file does not exist yet
(existing 47 renders are never touched).

Run: uv run python scripts/54_backfill_crest_256.py [--only slug1,slug2]
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CLUBS_JSON = ROOT / "frontend" / "public" / "data" / "clubs.json"
LOGO_DIR = ROOT / "data" / "logos"
ORIG_DIR = ROOT / "data" / "logos_orig"
SIZED_DIR = ROOT / "data" / "logos_sized"

SIZES = [256, 192]  # 256 drives selection; 192 is filled alongside if missing
RASTER_EXTS = (".png", ".jpg", ".jpeg", ".gif")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backfill_crest_256")


def source_for(slug: str) -> Path | None:
    """Best source for a slug — identical cascade to script 47."""
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


def render_raster_upscaled(img: Image.Image, size: int, dst: Path) -> None:
    """Fit inside size x size, aspect preserved — upscaling ALLOWED (LANCZOS)."""
    out = img.convert("RGBA")
    w, h = out.size
    scale = size / max(w, h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    save_quantized(out.resize((nw, nh), Image.LANCZOS), dst)


def run(only: set[str] | None = None) -> None:
    clubs = json.loads(CLUBS_JSON.read_text(encoding="utf-8"))
    slugs = sorted(c["slug"] for c in clubs)
    if only:
        slugs = [s for s in slugs if s in only]
    for size in SIZES:
        (SIZED_DIR / str(size)).mkdir(parents=True, exist_ok=True)

    stats = {"rendered": 0, "skipped_has_256": 0, "no_source": 0, "failed": 0}
    no_source: list[str] = []
    rendered_files: list[Path] = []
    for slug in slugs:
        if (SIZED_DIR / "256" / f"{slug}.png").exists():
            stats["skipped_has_256"] += 1
            continue
        src = source_for(slug)
        if not src:
            stats["no_source"] += 1
            no_source.append(slug)
            continue
        is_svg = src.suffix == ".svg"
        img = None
        if not is_svg:
            try:
                img = Image.open(src)
                img.load()
            except OSError as e:
                log.warning("unreadable source %s: %s", src, e)
                stats["failed"] += 1
                continue
        club_rendered = False
        for size in SIZES:
            dst = SIZED_DIR / str(size) / f"{slug}.png"
            if dst.exists():  # never touch existing (honest) 47 renders
                continue
            if is_svg:
                if not render_svg(src, size, dst):
                    continue
            else:
                render_raster_upscaled(img, size, dst)
            rendered_files.append(dst)
            club_rendered = True
        if club_rendered:
            stats["rendered"] += 1

    per_size = {s: sum(1 for _ in (SIZED_DIR / str(s)).glob("*.png")) for s in SIZES}
    log.info("done. %s tiers=%s files_written=%d", stats, per_size, len(rendered_files))
    if no_source:
        log.info("slugs with NO source at all: %s", ", ".join(no_source))
    # machine-readable list of what was written (for the CDN upload step)
    for f in rendered_files:
        print(f.relative_to(ROOT))


if __name__ == "__main__":
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    run(only)
