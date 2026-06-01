"""Download club logos from HNS Semafor for clubs that have a semafor_url but
no local logo file yet.

The main logo pipeline (scripts/07_fetch_logos.py) sources only from
hrnogomet-id and sofascore-id aliases. Clubs ingested straight from Semafor
(e.g. the 20 ŽNK in scripts/33_ingest_znk.py) have neither, so they fall back
to the ⚽ emoji. Semafor exposes a per-club logo on the hns.family CDN — this
script harvests it from the already-cached club pages.

Output: data/logos/<slug>.png  (same convention as 07_fetch_logos.py)
Idempotent: skips clubs that already have a non-empty logo file.

Run:
    uv run python scripts/34_fetch_semafor_logos.py
"""
from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402
from src.semafor import extract_club_id, parse_club_page  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("semafor_logos")

LOGO_DIR = ROOT / "data" / "logos"
CACHE = ROOT / "data" / "raw" / "semafor"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _to_png(data: bytes, dst: Path) -> bool:
    """Write image bytes to dst as PNG. Some Semafor logos are JPGs; convert
    them with macOS `sips` (this deploy runs locally on darwin)."""
    if data[:8] == PNG_MAGIC:
        dst.write_bytes(data)
        return True
    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as tmp:
        tmp.write(data)
        src = tmp.name
    try:
        subprocess.run(
            ["sips", "-s", "format", "png", src, "--out", str(dst)],
            check=True, capture_output=True,
        )
        return dst.exists() and dst.stat().st_size > 0
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    finally:
        Path(src).unlink(missing_ok=True)


def run() -> None:
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    conn = connect()
    rows = conn.execute(
        "SELECT slug, semafor_url FROM clubs WHERE semafor_url IS NOT NULL"
    ).fetchall()

    fetched = skipped = missing = failed = 0
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        for slug, url in rows:
            dst = LOGO_DIR / f"{slug}.png"
            if dst.exists() and dst.stat().st_size > 0:
                skipped += 1
                continue
            sid = extract_club_id(url)
            page = CACHE / f"{sid}.html"
            if not page.exists():
                missing += 1
                continue
            logo_url = parse_club_page(page.read_text(errors="ignore")).get("logo_url")
            if not logo_url:
                missing += 1
                continue
            try:
                r = client.get(logo_url)
                r.raise_for_status()
            except httpx.HTTPError as e:
                log.warning("fetch failed %s: %s", slug, e)
                failed += 1
                continue
            if not _to_png(r.content, dst):
                log.warning("could not save logo for %s (%s)", slug, logo_url)
                failed += 1
                continue
            fetched += 1
            log.info("logo %s (%d bytes)", slug, dst.stat().st_size)

    print(f"\nfetched={fetched} skipped={skipped} no-logo={missing} failed={failed}")


if __name__ == "__main__":
    run()
