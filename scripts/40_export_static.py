"""Export the SQLite catalog as static JSON for the React PWA frontend.

Writes:
    frontend/public/data/clubs.json     — flat array, one row per club + top-league info
    frontend/public/data/leagues.json   — array of leagues with club counts
    frontend/public/data/counties.json  — county list with counts
    frontend/public/data/stats.json     — global coverage numbers
    frontend/public/data/clubs/<slug>.json — per-club detail (leagues timeline, aliases)
    frontend/public/data/manifest.json  — { generated_at, counts, schema_version }

Logos are served from the c.ff.hr R2 CDN (see scripts/42-47); clubs.json
carries `logo_sizes` so the frontend can build density-aware srcset.

Run:
    uv run python scripts/40_export_static.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402

OUT_DIR = ROOT / "frontend" / "public" / "data"
LOGO_SRC = ROOT / "data" / "logos"

SCHEMA_VERSION = 1


def _ensure_dirs() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "clubs").mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, payload) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _logo_filename(slug: str) -> str | None:
    p = LOGO_SRC / f"{slug}.png"
    return p.name if p.exists() else None


SIZED_SRC = ROOT / "data" / "logos_sized"
LOGO_TIERS = [192, 256, 512, 1024]


def _logo_sizes(slug: str) -> list[int]:
    """Size tiers genuinely available on the c.ff.hr CDN (no upscaling)."""
    return [s for s in LOGO_TIERS if (SIZED_SRC / str(s) / f"{slug}.png").exists()]


def export_clubs(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
          c.id, c.slug, c.canonical_name, c.short_name,
          c.city, c.county, c.founded_year,
          c.stadium_name, c.stadium_capacity,
          c.website, c.email, c.phone, c.phone_kind, c.phone_e164,
          c.address, c.fb_url, c.ig_url, c.x_url,
          c.president, c.president_role,
          c.lat, c.lng,
          c.semafor_url, c.sofascore_url, c.registry_url, c.oib,
          (SELECT MIN(l.tier)
             FROM club_seasons cs JOIN leagues l ON l.id = cs.league_id
             WHERE cs.club_id = c.id) AS top_tier,
          (SELECT l.id
             FROM club_seasons cs JOIN leagues l ON l.id = cs.league_id
             WHERE cs.club_id = c.id
             ORDER BY l.tier ASC, cs.season DESC LIMIT 1) AS top_league_id,
          (SELECT l.name
             FROM club_seasons cs JOIN leagues l ON l.id = cs.league_id
             WHERE cs.club_id = c.id
             ORDER BY l.tier ASC, cs.season DESC LIMIT 1) AS top_league_name
        FROM clubs c
        ORDER BY c.canonical_name
        """
    ).fetchall()

    clubs = []
    for r in rows:
        d = dict(r)
        d["logo"] = _logo_filename(d["slug"])
        sizes = _logo_sizes(d["slug"])
        if sizes:
            d["logo_sizes"] = sizes
        # drop nulls to shrink payload (~30% smaller)
        clubs.append({k: v for k, v in d.items() if v not in (None, "")})
    return clubs


def export_leagues(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT l.id, l.name, l.tier, l.county, l.parent_id,
               COUNT(DISTINCT cs.club_id) AS club_count
        FROM leagues l
        LEFT JOIN club_seasons cs ON cs.league_id = l.id
        GROUP BY l.id
        ORDER BY l.tier, l.name
        """
    ).fetchall()
    return [{k: v for k, v in dict(r).items() if v not in (None, "")} for r in rows]


def export_counties(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT county AS name, COUNT(*) AS n
        FROM clubs WHERE county IS NOT NULL
        GROUP BY county ORDER BY n DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def export_stats(conn) -> dict:
    row = conn.execute(
        """
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN city IS NOT NULL THEN 1 ELSE 0 END) AS with_city,
          SUM(CASE WHEN county IS NOT NULL THEN 1 ELSE 0 END) AS with_county,
          SUM(CASE WHEN lat IS NOT NULL THEN 1 ELSE 0 END) AS with_geo,
          SUM(CASE WHEN phone_kind = 'mobile' THEN 1 ELSE 0 END) AS can_sms,
          SUM(CASE WHEN phone IS NOT NULL THEN 1 ELSE 0 END) AS can_call,
          SUM(CASE WHEN email IS NOT NULL THEN 1 ELSE 0 END) AS can_email,
          SUM(CASE WHEN address IS NOT NULL THEN 1 ELSE 0 END) AS can_mail,
          SUM(CASE WHEN
            website IS NOT NULL OR fb_url IS NOT NULL OR ig_url IS NOT NULL
            THEN 1 ELSE 0 END) AS can_web,
          SUM(CASE WHEN
            phone_kind = 'mobile' AND phone IS NOT NULL
            AND email IS NOT NULL AND address IS NOT NULL
            AND (website IS NOT NULL OR fb_url IS NOT NULL OR ig_url IS NOT NULL)
            THEN 1 ELSE 0 END) AS full_contact,
          SUM(CASE WHEN
            phone IS NULL AND email IS NULL AND address IS NULL
            AND website IS NULL AND fb_url IS NULL AND ig_url IS NULL
            THEN 1 ELSE 0 END) AS unreachable,
          SUM(CASE WHEN founded_year IS NOT NULL THEN 1 ELSE 0 END) AS with_founded,
          SUM(CASE WHEN stadium_name IS NOT NULL THEN 1 ELSE 0 END) AS with_stadium,
          SUM(CASE WHEN president IS NOT NULL THEN 1 ELSE 0 END) AS with_president,
          SUM(CASE WHEN oib IS NOT NULL THEN 1 ELSE 0 END) AS with_oib
        FROM clubs
        """
    ).fetchone()
    g = dict(row)

    tiers = conn.execute(
        """
        SELECT top_tier AS tier, COUNT(*) AS n FROM (
          SELECT (SELECT MIN(l.tier)
                    FROM club_seasons cs JOIN leagues l ON l.id = cs.league_id
                    WHERE cs.club_id = c.id) AS top_tier
          FROM clubs c
        ) WHERE tier IS NOT NULL
        GROUP BY tier ORDER BY tier
        """
    ).fetchall()

    return {
        "global": g,
        "tiers": [dict(r) for r in tiers],
    }


def export_club_details(conn, club_ids: list[int]) -> int:
    n = 0
    for cid in club_ids:
        club = conn.execute("SELECT * FROM clubs WHERE id = ?", (cid,)).fetchone()
        if not club:
            continue
        slug = club["slug"]
        seasons = conn.execute(
            """
            SELECT cs.season, cs.source, l.id AS league_id, l.name AS league_name,
                   l.tier, l.county
            FROM club_seasons cs JOIN leagues l ON l.id = cs.league_id
            WHERE cs.club_id = ?
            ORDER BY cs.season DESC, l.tier ASC
            """,
            (cid,),
        ).fetchall()
        aliases = conn.execute(
            """
            SELECT alias, source FROM club_aliases
            WHERE club_id = ? AND source NOT LIKE '%-id'
            ORDER BY alias
            """,
            (cid,),
        ).fetchall()
        payload = {
            "id": cid,
            "slug": slug,
            "seasons": [dict(r) for r in seasons],
            "aliases": [dict(r) for r in aliases],
        }
        _write_json(OUT_DIR / "clubs" / f"{slug}.json", payload)
        n += 1
    return n


def main() -> None:
    _ensure_dirs()
    with connect() as conn:
        clubs = export_clubs(conn)
        leagues = export_leagues(conn)
        counties = export_counties(conn)
        stats = export_stats(conn)
        club_ids = [c["id"] for c in clubs]
        details_n = export_club_details(conn, club_ids)

    _write_json(OUT_DIR / "clubs.json", clubs)
    _write_json(OUT_DIR / "leagues.json", leagues)
    _write_json(OUT_DIR / "counties.json", counties)
    _write_json(OUT_DIR / "stats.json", stats)
    _write_json(
        OUT_DIR / "manifest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "counts": {
                "clubs": len(clubs),
                "leagues": len(leagues),
                "counties": len(counties),
                "club_details": details_n,
            },
        },
    )

    print(
        f"clubs={len(clubs)} leagues={len(leagues)} counties={len(counties)} "
        f"details={details_n}"
    )


if __name__ == "__main__":
    main()
