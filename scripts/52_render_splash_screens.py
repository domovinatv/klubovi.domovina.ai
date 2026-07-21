"""Render per-club iOS PWA splash screens (apple-touch-startup-image).

Every club's wallet at {slug}.ff.hr is installable as a PWA; without per-device
apple-touch-startup-image PNGs iOS shows a black screen while the app boots.
This renders, for every club that script 50 covers, one splash per iOS device
class: data/club_splash/{W}x{H}/{slug}.png.

Composition (per splash):
  - full-bleed background = the SAME per-club color script 50 picks for the
    square icon (prepare_crest -> forced bg, else background_for)
  - crest cut-out centered horizontally, contained in a box of 34% of the
    splash WIDTH (aspect preserved, LANCZOS, upscaling allowed)
  - vertical center slightly above optical center: crest center at 45% height
  - opaque RGB, 256-color quantized (same save pattern as scripts 47/49/50)

Crest cut-out + background heuristic are IMPORTED from script 50 (single
source of truth), which in turn imports the color analysis from script 48.
The expensive work (source cascade, keying, clustering) runs ONCE per club;
the crest master is fitted to the largest needed box and scaled down per size.

CDN keys mirror the dirs: https://c.ff.hr/club_splash/{W}x{H}/{slug}.png —
NEW keys, additive backfill (see scripts/53_upload_splash.sh).

Idempotent per source mtime. Run:
  uv run python scripts/52_render_splash_screens.py [--only slug1,slug2] [--workers N]
"""
from __future__ import annotations

import importlib.util
import logging
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "club_splash"

# iOS device classes (portrait, px). Landscape is derivable client-side by
# swapping W/H in the media query; we ship portrait only.
SIZES: list[tuple[int, int]] = [
    (640, 1136), (750, 1334), (828, 1792), (1125, 2436),
    (1170, 2532), (1179, 2556), (1206, 2622), (1242, 2208),
    (1242, 2688), (1284, 2778), (1290, 2796), (1320, 2868),
]

CREST_FRAC = 0.34     # crest box = 34% of splash width
CENTER_Y_FRAC = 0.45  # crest vertical center, slightly above optical center
MAX_BOX = max(int(w * CREST_FRAC) for w, _h in SIZES)  # largest crest box

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("render_splash")

# script 50 owns the crest cut-out + background heuristic; module name starts
# with a digit so it has to come in via importlib
_spec = importlib.util.spec_from_file_location(
    "square_icons", ROOT / "scripts" / "50_render_square_icons.py"
)
_sq = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sq)


def render_club(slug: str) -> str:
    """Render all splash sizes for one club. Returns a status keyword."""
    src = _sq.source_for(slug)
    if not src:
        return "no_source"
    src_mtime = src.stat().st_mtime
    dsts = {(w, h): OUT_DIR / f"{w}x{h}" / f"{slug}.png" for w, h in SIZES}
    if all(d.exists() and d.stat().st_mtime >= src_mtime for d in dsts.values()):
        return "skipped_fresh"

    try:
        crest, forced_bg = _sq.prepare_crest(src)
        bg = forced_bg or _sq.background_for(crest)
    except OSError as e:
        log.warning("failed %s: %s", slug, e)
        return "failed"

    # fit the crest once at the largest needed box, scale down per size
    w0, h0 = crest.size
    scale0 = min(MAX_BOX / w0, MAX_BOX / h0)
    mw, mh = max(1, round(w0 * scale0)), max(1, round(h0 * scale0))
    master = crest.resize((mw, mh), Image.LANCZOS)

    for (w, h), dst in dsts.items():
        box = int(w * CREST_FRAC)
        k = box / MAX_BOX
        nw, nh = max(1, round(mw * k)), max(1, round(mh * k))
        fitted = master if (nw, nh) == (mw, mh) else master.resize((nw, nh), Image.LANCZOS)
        canvas = Image.new("RGB", (w, h), bg)
        canvas.paste(fitted, ((w - nw) // 2, round(h * CENTER_Y_FRAC - nh / 2)), mask=fitted)
        _sq.save_quantized(canvas, dst)
    return "rendered"


def run(only: set[str] | None = None, workers: int | None = None) -> None:
    slugs = sorted(p.stem for p in _sq.LOGO_DIR.glob("*.png"))
    if only:
        slugs = [s for s in slugs if s in only]
    for w, h in SIZES:
        (OUT_DIR / f"{w}x{h}").mkdir(parents=True, exist_ok=True)

    workers = workers or min(8, os.cpu_count() or 4)
    stats = {"rendered": 0, "skipped_fresh": 0, "no_source": 0, "failed": 0}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(render_club, s): s for s in slugs}
        for i, fut in enumerate(as_completed(futs), 1):
            stats[fut.result()] += 1
            if i % 100 == 0:
                log.info("progress %d/%d %s", i, len(slugs), stats)

    per_size = {f"{w}x{h}": sum(1 for _ in (OUT_DIR / f"{w}x{h}").glob("*.png")) for w, h in SIZES}
    log.info("done. %s per_size=%s", stats, per_size)


if __name__ == "__main__":
    only = None
    workers = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    if "--workers" in sys.argv:
        workers = int(sys.argv[sys.argv.index("--workers") + 1])
    run(only, workers)
