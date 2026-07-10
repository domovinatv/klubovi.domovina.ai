"""Render 1024x1024 square app icons (opaque, per-club background color).

Purpose: every club's wallet at {slug}.ff.hr is installable as a PWA; iOS and
Android home-screen icons need a SQUARE, OPAQUE image with the crest centered
on a background color that actually suits that crest (one shared background
does not fit 1014 heraldic palettes).

Source cascade (best first, same spirit as script 47): logos_orig/{slug}.svg,
then the largest raster among logos_orig/{slug}.{png,jpg,jpeg,gif,bmp} and the
legacy data/logos/{slug}.png. Upscaling is allowed (LANCZOS) — home-screen
icons display at <= ~180 px, so a 1024 master from a small crest is fine
(precedent: script 49).

Crest cut-out. Three source classes (measured on the full catalog:
4 svg / 502 alpha cut-out / 386 opaque white-corner / 122 opaque other):

  - SVG + real alpha cut-outs are used as-is.
  - Opaque images with near-white corners get border flood-fill keying: white
    is removed only where it is reachable from the image border, so internal
    white crest fills survive (a global white->transparent pass would punch
    holes in them).
  - Opaque images with a uniform NON-white corner color keep their native
    background — the icon background simply extends that color seamlessly.
  - Anything else (photo-like, gradient corners) is placed unkeyed on white.

Background heuristic (for cut-out crests):
  1. brand primary from script 48's cluster analysis (imported, not copied)
  2. crest mean luminance decides polarity: light crest (>= 0.60) sits on the
     ensure_dark()'d primary; dark crest sits on a light tint of the primary
     (HSL: S*0.35, L=0.93)
  3. greyscale crests (no saturated cluster) get neutral #F2F4F6 / #263244
  4. contrast guard: if |bg_lum - crest_lum| < 0.15 flip to the other polarity

Variants (both 1024, opaque RGB, 256-color quantized like the catalog):
  - data/club_square/{slug}.png           crest in a 70% box (iOS/general;
                                          iOS rounds corners itself)
  - data/club_square/maskable/{slug}.png  crest in a 56% box (Android
                                          adaptive-icon safe zone, see
                                          script 49's derivation)

CDN keys mirror the dirs: https://c.ff.hr/club_square/{slug}.png and
https://c.ff.hr/club_square/maskable/{slug}.png — NEW keys, so the backfill is
additive and never hits the 30-day edge-cache staleness trap (LOGOS.md).

Idempotent per mtime. Run:
  uv run python scripts/50_render_square_icons.py [--only slug1,slug2]
"""
from __future__ import annotations

import importlib.util
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
LOGO_DIR = ROOT / "data" / "logos"
ORIG_DIR = ROOT / "data" / "logos_orig"
OUT_DIR = ROOT / "data" / "club_square"

RASTER_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp")
CANVAS = 1024
# variant subdir ("" = root) -> crest box fraction
VARIANTS: dict[str, float] = {"": 0.70, "maskable": 0.56}

ALPHA_CUT = 128     # alpha below this counts as transparent
WHITE_KEY = 230     # border flood-fill: all channels above -> keyable white
CORNER_UNIFORM = 30 # max per-channel spread for "uniform corner color"
LIGHT_CREST = 0.60  # mean luminance above -> crest needs a dark background
CONTRAST_MIN = 0.15 # minimum |bg_lum - crest_lum|
NEUTRAL_LIGHT = (242, 244, 246)
NEUTRAL_DARK = (38, 50, 68)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("render_square")

# script 48 owns the crest color analysis; module name starts with a digit so
# it has to come in via importlib
_spec = importlib.util.spec_from_file_location(
    "app_configs", ROOT / "scripts" / "48_export_app_configs.py"
)
_ac = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ac)


# --- source selection --------------------------------------------------------

def source_for(slug: str) -> Path | None:
    svg = ORIG_DIR / f"{slug}.svg"
    if svg.exists():
        return svg
    cands = [ORIG_DIR / f"{slug}{e}" for e in RASTER_EXTS if (ORIG_DIR / f"{slug}{e}").exists()]
    legacy = LOGO_DIR / f"{slug}.png"
    if legacy.exists():
        cands.append(legacy)
    if not cands:
        return None

    def max_dim(p: Path) -> int:
        try:
            with Image.open(p) as im:
                return max(im.size)
        except OSError:
            return 0

    return max(cands, key=max_dim)


def render_svg_crest(src: Path, box: int) -> Image.Image | None:
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        try:
            subprocess.run(
                ["rsvg-convert", "-w", str(box), "-h", str(box),
                 "--keep-aspect-ratio", str(src), "-o", tmp.name],
                check=True, capture_output=True,
            )
            img = Image.open(tmp.name)
            img.load()
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
            log.warning("svg render failed %s: %s", src.name, e)
            return None
    return img.convert("RGBA")


# --- cut-out ------------------------------------------------------------------

def is_cutout(img: Image.Image) -> bool:
    alpha = img.getchannel("A")
    if alpha.getextrema()[0] >= 250:
        return False
    w, h = img.size
    corners = [alpha.getpixel(xy) for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    return sum(1 for a in corners if a < ALPHA_CUT) >= 3


def corner_colors(img: Image.Image) -> list[tuple[int, int, int]]:
    rgb = img.convert("RGB")
    w, h = rgb.size
    return [rgb.getpixel(xy) for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]


def key_border_white(img: Image.Image) -> Image.Image:
    """Make border-reachable near-white transparent (BFS flood fill).

    Internal whites (crest fills) stay opaque because the fill can only enter
    through near-white paths connected to the image border.
    """
    rgba = img.convert("RGBA")
    w, h = rgba.size
    px = rgba.load()

    def keyable(x: int, y: int) -> bool:
        r, g, b, a = px[x, y]
        return a > 0 and r > WHITE_KEY and g > WHITE_KEY and b > WHITE_KEY

    seen = bytearray(w * h)
    stack = [
        (x, y)
        for x in range(w) for y in (0, h - 1)
        if keyable(x, y)
    ] + [
        (x, y)
        for y in range(h) for x in (0, w - 1)
        if keyable(x, y)
    ]
    for x, y in stack:
        seen[y * w + x] = 1
    while stack:
        x, y = stack.pop()
        r, g, b, _a = px[x, y]
        px[x, y] = (r, g, b, 0)
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx] and keyable(nx, ny):
                seen[ny * w + nx] = 1
                stack.append((nx, ny))
    return rgba


def trim_to_content(img: Image.Image) -> Image.Image:
    bbox = img.getchannel("A").getbbox()
    return img.crop(bbox) if bbox else img


# --- background ---------------------------------------------------------------

def crest_luminance(img: Image.Image) -> float:
    data = [
        _ac.rel_luminance((r, g, b))
        for r, g, b, a in img.getdata()
        if a >= ALPHA_CUT
    ]
    return sum(data) / len(data) if data else 0.5


def background_for(crest: Image.Image) -> tuple[int, int, int]:
    """Pick the icon background from the cut-out crest itself.

    Clusters are computed on a 256px thumbnail of the crest (written to a temp
    file because script 48's crest_clusters is path-based) — this keeps the
    analysis on exactly what will be composited, keyed background excluded.
    """
    lum = crest_luminance(crest)
    thumb = crest.copy()
    thumb.thumbnail((256, 256), Image.LANCZOS)
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        thumb.save(tmp.name, "PNG")
        clusters = _ac.crest_clusters(Path(tmp.name))
    saturated = [rgb for rgb, _s in clusters if _ac.hsv_of(rgb)[1] >= _ac.SAT_MIN]

    if not saturated:  # greyscale crest
        return NEUTRAL_DARK if lum >= LIGHT_CREST else NEUTRAL_LIGHT

    primary = saturated[0]
    h, s, _l = _ac.hsl_of(primary)
    dark_bg = _ac.ensure_dark(primary)
    light_bg = _ac.rgb_from_hsl(h, s * 0.35, 0.93)

    bg = dark_bg if lum >= LIGHT_CREST else light_bg
    if abs(_ac.rel_luminance(bg) - lum) < CONTRAST_MIN:
        bg = light_bg if bg == dark_bg else dark_bg
    return bg


# --- composition --------------------------------------------------------------

def save_quantized(img: Image.Image, dst: Path) -> None:
    img.convert("RGB").quantize(colors=256, method=Image.Quantize.FASTOCTREE).save(
        dst, "PNG", optimize=True
    )


def compose(crest: Image.Image, bg: tuple[int, int, int], box_frac: float, dst: Path) -> None:
    box = int(CANVAS * box_frac)
    w, h = crest.size
    scale = min(box / w, box / h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    fitted = crest.resize((nw, nh), Image.LANCZOS)

    canvas = Image.new("RGB", (CANVAS, CANVAS), bg)
    canvas.paste(fitted, ((CANVAS - nw) // 2, (CANVAS - nh) // 2), mask=fitted)
    save_quantized(canvas, dst)


def prepare_crest(src: Path) -> tuple[Image.Image, tuple[int, int, int] | None]:
    """Load + cut out the crest. Returns (RGBA crest, forced bg or None).

    forced bg is set for opaque sources whose own background must be kept:
    a uniform non-white corner color extends into the icon background; a
    non-uniform (photo/gradient) source forces white.
    """
    if src.suffix == ".svg":
        img = render_svg_crest(src, int(CANVAS * max(VARIANTS.values())))
        if img is None:
            raise OSError(f"rsvg-convert failed for {src}")
        return trim_to_content(img), None

    img = Image.open(src)
    img.load()
    img = img.convert("RGBA")
    if is_cutout(img):
        return trim_to_content(img), None

    corners = corner_colors(img)
    if all(all(ch > _ac.WHITE_MIN for ch in c) for c in corners):
        return trim_to_content(key_border_white(img)), None

    spread = max(
        max(c[i] for c in corners) - min(c[i] for c in corners) for i in range(3)
    )
    if spread <= CORNER_UNIFORM:  # uniform native background -> extend it
        avg = tuple(round(sum(c[i] for c in corners) / 4) for i in range(3))
        return img, avg
    return img, (255, 255, 255)  # photo-like: unkeyed on white


def run(only: set[str] | None = None) -> None:
    slugs = sorted(p.stem for p in LOGO_DIR.glob("*.png"))
    if only:
        slugs = [s for s in slugs if s in only]
    for sub in VARIANTS:
        (OUT_DIR / sub).mkdir(parents=True, exist_ok=True)

    stats = {"rendered": 0, "skipped_fresh": 0, "no_source": 0, "failed": 0}
    for slug in slugs:
        src = source_for(slug)
        if not src:
            stats["no_source"] += 1
            continue
        src_mtime = src.stat().st_mtime
        dsts = {sub: OUT_DIR / sub / f"{slug}.png" for sub in VARIANTS}
        if all(d.exists() and d.stat().st_mtime >= src_mtime for d in dsts.values()):
            stats["skipped_fresh"] += 1
            continue
        try:
            crest, forced_bg = prepare_crest(src)
            bg = forced_bg or background_for(crest)
        except OSError as e:
            log.warning("failed %s: %s", slug, e)
            stats["failed"] += 1
            continue
        for sub, box_frac in VARIANTS.items():
            compose(crest, bg, box_frac, dsts[sub])
        stats["rendered"] += 1

    per_variant = {sub or ".": sum(1 for _ in (OUT_DIR / sub).glob("*.png")) for sub in VARIANTS}
    log.info("done. %s variants=%s", stats, per_variant)


if __name__ == "__main__":
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    run(only)
