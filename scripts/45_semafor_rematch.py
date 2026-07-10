"""Match still-unmatched Semafor cache pages to clubs and pull their logos.

The Semafor BFS crawl (17c) cached ~1078 club pages but only ~630 got a
semafor_url in the DB — the rest fell out as ambiguous. The NK Lomnica case
showed those orphaned pages can hide strictly better logos. This script
re-runs the match conservatively:

  match rule: normalized name equality (prefix + diacritics stripped), and
    - exactly one name candidate whose city is compatible (equal, or one side
      missing while the name candidate set has size 1), or
    - multiple name candidates disambiguated by exact city equality.
  City on the Semafor side comes from the address field or the tail of
  full_name ("Nogometni klub X, <city>").

For every new match: set clubs.semafor_url, then fetch the CDN original
(same URL derivation as scripts/42_upgrade_logos.py) and apply it when it
beats the current file by MIN_UPGRADE_FACTOR. Full-res goes to
data/logos_orig/, quantized web PNG to data/logos/.

Run: uv run python scripts/45_semafor_rematch.py [--dry-run]
"""
from __future__ import annotations

import importlib.util
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402
from src.normalize import strip_diacritics, _PREFIX_RE  # noqa: E402
from src.semafor import parse_club_page, extract_club_id, canonical_url, city_from_address  # noqa: E402

_spec = importlib.util.spec_from_file_location("upgrade42", ROOT / "scripts" / "42_upgrade_logos.py")
_u42 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_u42)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("semafor_rematch")

CACHE = ROOT / "data" / "raw" / "semafor"


def norm(s: str | None) -> str:
    if not s:
        return ""
    return " ".join(strip_diacritics(_PREFIX_RE.sub("", s.strip())).lower().split())


def semafor_city(info: dict) -> str:
    city = city_from_address(info.get("address"))
    if city:
        return norm(city)
    full = info.get("full_name") or ""
    if "," in full:
        return norm(full.rsplit(",", 1)[1])
    return ""


def run(dry_run: bool = False) -> None:
    conn = connect()
    taken_sids = {
        extract_club_id(r["semafor_url"])
        for r in conn.execute("SELECT semafor_url FROM clubs WHERE semafor_url IS NOT NULL")
    }
    unmatched_clubs = conn.execute(
        "SELECT id, slug, canonical_name, city FROM clubs WHERE semafor_url IS NULL"
    ).fetchall()
    by_name: dict[str, list] = defaultdict(list)
    for c in unmatched_clubs:
        by_name[norm(c["canonical_name"])].append(c)

    stats = {"matched": 0, "ambiguous": 0, "no_name_hit": 0, "upgraded": 0, "no_gain": 0, "no_logo": 0, "fetch_fail": 0}
    matches: list[tuple] = []  # (club_row, sid, info)
    for page in sorted(CACHE.glob("*.html")):
        sid = int(page.stem)
        if sid in taken_sids:
            continue
        info = parse_club_page(page.read_text(errors="ignore"))
        name = norm(info.get("short_name") or info.get("full_name"))
        if not name or name not in by_name:
            stats["no_name_hit"] += 1
            continue
        cands = by_name[name]
        s_city = semafor_city(info)
        compatible = [
            c for c in cands
            if s_city and norm(c["city"]) == s_city
        ]
        if len(compatible) != 1:
            if len(cands) == 1 and (not s_city or not cands[0]["city"]):
                compatible = cands  # unique name, one side missing city
            else:
                stats["ambiguous"] += 1
                log.debug("ambiguous %s (sid %d, city %r, %d cands)", name, sid, s_city, len(cands))
                continue
        club = compatible[0]
        matches.append((club, sid, info))
        by_name[name].remove(club)  # one page per club
        stats["matched"] += 1

    log.info("new matches: %d", stats["matched"])
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        for club, sid, info in matches:
            url = canonical_url(sid)
            if not dry_run:
                conn.execute(
                    "UPDATE clubs SET semafor_url=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (url, club["id"]),
                )
            logo_url = info.get("logo_url")
            if not logo_url:
                stats["no_logo"] += 1
                continue
            got = None
            for cand in _u42.original_candidates(logo_url):
                got = _u42.fetch_image(client, cand)
                if got:
                    break
                time.sleep(0.05)
            if not got:
                stats["fetch_fail"] += 1
                continue
            blob, img = got
            old_dim, new_dim = _u42.current_max_dim(club["slug"]), max(img.size)
            if new_dim < old_dim * _u42.MIN_UPGRADE_FACTOR:
                stats["no_gain"] += 1
                continue
            if dry_run:
                log.info("[dry] %s: %dpx -> %dpx (sid %d)", club["slug"], old_dim, new_dim, sid)
            else:
                ext = (img.format or "png").lower().replace("jpeg", "jpg")
                for old in _u42.ORIG_DIR.glob(f"{club['slug']}.*"):
                    old.unlink()
                (_u42.ORIG_DIR / f"{club['slug']}.{ext}").write_bytes(blob)
                _u42.write_web_png(img, _u42.LOGO_DIR / f"{club['slug']}.png")
                log.info("%s: %dpx -> %dpx (sid %d)", club["slug"], old_dim, new_dim, sid)
            stats["upgraded"] += 1
            time.sleep(0.05)
    if not dry_run:
        conn.commit()
    log.info("done. %s", stats)


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
