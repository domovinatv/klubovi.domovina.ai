"""Export app-ready club configs for the white-label wallet app.

Reads frontend/public/data/clubs.json (the canonical static export) and emits
data/export/clubs-app.json: one compact record per club with identity fields
(name, shortName, town, county, founded, league, oib), a `crest` flag
(true iff data/logos_sized/256/{slug}.png exists) and — where a crest exists
and its colors pass sanity checks — a crest-derived brand palette
{primaryHex, accentHex, pageHex} matching the hand-tuned style of the wallet
prototype (e.g. lomnica #1F4FA3/#D32030/#F3F6FC).

Color heuristic (per crest, 256px RGBA):
  1. keep pixels with alpha >= 128; drop near-white (all ch > 235) and
     near-black (all ch < 25)
  2. median-cut quantize the remainder to 8 clusters, ordered by pixel share
  3. primaryHex  = most frequent cluster with HSV saturation >= 0.25
                   (crests are heraldic; primary must be a color, not grey);
                   no such cluster -> `brand` omitted, app falls back to its
                   neutral palette
  4. accentHex   = next cluster with sat >= 0.25 and (hue delta >= 30 deg OR
                   HSL lightness delta >= 0.25 vs primary); none -> primary
                   darkened ~35% at same hue (single-color crests)
  5. pageHex     = very light tint of primary (HSL: S*0.30, L=0.96)
  6. sanity      = primary/accent must carry white text (relative luminance
                   < 0.6); too light -> re-set at HSL L=0.45, then keep
                   stepping L down until the cap holds (yellows/cyans stay
                   too luminous at L=0.45)

Calibration: prints generated vs hand-picked colors for the 4 reference clubs
(lomnica, lukavec, croatia-zmijavci, mladost-okic-klinca-sela) with hue
distance — informational only, never fails the run.

Idempotent: pure function of clubs.json + logos_sized/256; safe to re-run.

Run: uv run python scripts/48_export_app_configs.py
"""
from __future__ import annotations

import colorsys
import json
import logging
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CLUBS_JSON = ROOT / "frontend" / "public" / "data" / "clubs.json"
CREST_DIR = ROOT / "data" / "logos_sized" / "256"
OUT_PATH = ROOT / "data" / "export" / "clubs-app.json"

ALPHA_MIN = 128
WHITE_MIN = 235   # all channels above -> near-white, dropped
BLACK_MAX = 25    # all channels below -> near-black, dropped
N_CLUSTERS = 8
SAT_MIN = 0.25    # HSV saturation floor for "a real heraldic color"
HUE_DELTA_MIN = 30.0   # degrees
LIGHT_DELTA_MIN = 0.25  # HSL lightness delta as accent fallback criterion
ACCENT_SHARE_MIN = 0.10  # accent cluster must cover >=10% of colored pixels
                         # (croatia-zmijavci: tiny navy detail must NOT beat
                         #  the darker-red fallback on a red-only crest)
LUM_MAX = 0.6     # primary must be darker than this (white text on top)
SHORT_NAME_MAX = 14

# hand-picked references from the wallet prototype (primary, accent)
CALIBRATION = {
    "lomnica": ("#1F4FA3", "#D32030"),
    "lukavec": ("#1F6BB5", "#D5202A"),
    "croatia-zmijavci": ("#E1121C", "#8E1116"),
    "mladost-okic-klinca-sela": ("#D4202C", "#1F3A8A"),
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("export_app_configs")


# --- color helpers -----------------------------------------------------------

def hex_of(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def hsv_of(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    return colorsys.rgb_to_hsv(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)


def hsl_of(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    h, l, s = colorsys.rgb_to_hls(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)
    return h, s, l


def rgb_from_hsl(h: float, s: float, l: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return round(r * 255), round(g * 255), round(b * 255)


def rel_luminance(rgb: tuple[int, int, int]) -> float:
    def ch(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def hue_dist_deg(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    d = abs(hsv_of(a)[0] - hsv_of(b)[0]) * 360
    return min(d, 360 - d)


def ensure_dark(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Darken until the color can carry white text (rel. luminance < LUM_MAX).

    HSL L=0.45 is the first stop (matches hand-picked palettes for red/blue
    crests) but is NOT enough for yellow/cyan hues (a saturated yellow at
    L=0.45 still has luminance ~0.7), so keep stepping L down until the cap
    actually holds.
    """
    if rel_luminance(rgb) < LUM_MAX:
        return rgb
    h, s, _l = hsl_of(rgb)
    l = 0.45
    out = rgb_from_hsl(h, s, l)
    while rel_luminance(out) >= LUM_MAX and l > 0.15:
        l -= 0.05
        out = rgb_from_hsl(h, s, l)
    return out


# --- crest analysis ----------------------------------------------------------

def crest_clusters(path: Path) -> list[tuple[tuple[int, int, int], float]]:
    """Dominant color clusters of a crest, ordered by pixel share (desc)."""
    img = Image.open(path).convert("RGBA")
    px = [
        (r, g, b)
        for r, g, b, a in img.getdata()
        if a >= ALPHA_MIN
        and not (r > WHITE_MIN and g > WHITE_MIN and b > WHITE_MIN)
        and not (r < BLACK_MAX and g < BLACK_MAX and b < BLACK_MAX)
    ]
    if len(px) < 32:
        return []
    strip = Image.new("RGB", (len(px), 1))
    strip.putdata(px)
    q = strip.quantize(colors=N_CLUSTERS, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    counts = sorted(q.getcolors(maxcolors=N_CLUSTERS), reverse=True)
    total = len(px)
    return [
        (tuple(pal[i * 3 : i * 3 + 3]), n / total)
        for n, i in counts
    ]


def derive_brand(path: Path) -> dict[str, str] | None:
    clusters = crest_clusters(path)
    saturated = [(rgb, share) for rgb, share in clusters if hsv_of(rgb)[1] >= SAT_MIN]
    if not saturated:
        return None
    primary = saturated[0][0]

    accent = None
    p_l = hsl_of(primary)[2]
    for rgb, share in saturated[1:]:
        if share < ACCENT_SHARE_MIN:
            continue
        if hue_dist_deg(rgb, primary) >= HUE_DELTA_MIN or abs(hsl_of(rgb)[2] - p_l) >= LIGHT_DELTA_MIN:
            accent = rgb
            break

    # sanity: primary (and accent) must carry white text
    primary = ensure_dark(primary)

    if accent is None:  # single-color crest -> darker same-hue accent
        h, s, l = hsl_of(primary)
        accent = rgb_from_hsl(h, s, l * 0.65)
    else:
        accent = ensure_dark(accent)

    h, s, _l = hsl_of(primary)
    page = rgb_from_hsl(h, s * 0.30, 0.96)

    return {"primaryHex": hex_of(primary), "accentHex": hex_of(accent), "pageHex": hex_of(page)}


# --- export ------------------------------------------------------------------

def build_record(club: dict, brand: dict | None, crest: bool) -> dict:
    rec: dict = {
        "slug": club["slug"],
        "name": club["canonical_name"],
        "shortName": (club.get("short_name") or club["canonical_name"]).strip()[:SHORT_NAME_MAX].strip(),
    }
    if club.get("city"):
        rec["town"] = club["city"]
    if club.get("county"):
        rec["county"] = club["county"]
    if club.get("founded_year"):
        rec["founded"] = str(club["founded_year"])
    if club.get("top_league_name"):
        rec["league"] = club["top_league_name"]
    if club.get("oib"):
        rec["oib"] = club["oib"]
    rec["crest"] = crest
    if brand:
        rec["brand"] = brand
    return rec


def run() -> None:
    clubs = json.loads(CLUBS_JSON.read_text(encoding="utf-8"))
    log.info("loaded %d clubs from %s", len(clubs), CLUBS_JSON)

    records = []
    n_crest = n_brand = 0
    no_brand_with_crest: list[str] = []
    for club in sorted(clubs, key=lambda c: c["slug"]):
        slug = club["slug"]
        crest_path = CREST_DIR / f"{slug}.png"
        crest = crest_path.exists()
        brand = None
        if crest:
            n_crest += 1
            brand = derive_brand(crest_path)
            if brand:
                n_brand += 1
            else:
                no_brand_with_crest.append(slug)
        records.append(build_record(club, brand, crest))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    log.info("wrote %s (%.0f KB)", OUT_PATH, OUT_PATH.stat().st_size / 1024)
    log.info(
        "summary: total=%d crest=%d brand=%d crest-but-no-brand=%d no-crest=%d",
        len(records), n_crest, n_brand, len(no_brand_with_crest), len(records) - n_crest,
    )
    if no_brand_with_crest:
        log.info("crest without brand (greyscale/low-sat crests): %s", ", ".join(no_brand_with_crest))

    # calibration report (informational)
    by_slug = {r["slug"]: r for r in records}
    print("\nCalibration vs hand-picked references:")
    print(f"{'slug':<28} {'gen primary':<12} {'ref primary':<12} {'dH':>5}   {'gen accent':<12} {'ref accent':<12} {'dH':>5}")
    for slug, (ref_p, ref_a) in CALIBRATION.items():
        rec = by_slug.get(slug)
        if not rec or "brand" not in rec:
            print(f"{slug:<28} NO BRAND GENERATED (ref {ref_p}/{ref_a})")
            continue
        b = rec["brand"]
        def rgb(hx: str) -> tuple[int, int, int]:
            return tuple(int(hx[i : i + 2], 16) for i in (1, 3, 5))
        dp = hue_dist_deg(rgb(b["primaryHex"]), rgb(ref_p))
        da = hue_dist_deg(rgb(b["accentHex"]), rgb(ref_a))
        print(f"{slug:<28} {b['primaryHex']:<12} {ref_p:<12} {dp:4.0f}°   {b['accentHex']:<12} {ref_a:<12} {da:4.0f}°")


if __name__ == "__main__":
    run()
