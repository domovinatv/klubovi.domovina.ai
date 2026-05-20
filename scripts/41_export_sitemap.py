"""Generate sitemap.xml + robots.txt into frontend/public/ from the SQLite catalog.

Run after 40_export_static.py — frontend/public/data/clubs.json must exist.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PUBLIC = ROOT / "frontend" / "public"
SITE = "https://klubovi.domovina.ai"


def main() -> None:
    clubs = json.loads((PUBLIC / "data" / "clubs.json").read_text())
    counties = json.loads((PUBLIC / "data" / "counties.json").read_text())
    leagues = json.loads((PUBLIC / "data" / "leagues.json").read_text())

    today = datetime.now(timezone.utc).date().isoformat()
    urls: list[tuple[str, str, str]] = [
        ("/", "1.0", "weekly"),
        ("/karta", "0.9", "weekly"),
        ("/statistika", "0.8", "monthly"),
        ("/o-projektu", "0.5", "yearly"),
    ]
    for c in clubs:
        urls.append((f"/klub/{c['slug']}", "0.7", "monthly"))
    for c in counties:
        from urllib.parse import quote
        urls.append((f"/zupanija/{quote(c['name'])}", "0.6", "monthly"))
    for lg in leagues:
        urls.append((f"/liga/{lg['id']}", "0.6", "monthly"))

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path, prio, freq in urls:
        parts.append(
            "<url>"
            f"<loc>{SITE}{escape(path)}</loc>"
            f"<lastmod>{today}</lastmod>"
            f"<changefreq>{freq}</changefreq>"
            f"<priority>{prio}</priority>"
            "</url>"
        )
    parts.append("</urlset>")

    (PUBLIC / "sitemap.xml").write_text("\n".join(parts), encoding="utf-8")
    (PUBLIC / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n\nSitemap: " + SITE + "/sitemap.xml\n",
        encoding="utf-8",
    )
    print(f"sitemap_urls={len(urls)}")


if __name__ == "__main__":
    main()
