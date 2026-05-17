"""Extract venue coordinates from the SofaScore raw cache.

Each team detail JSON (data/raw/sofascore/teams/{id}.json) carries a
venue.venueCoordinates {latitude, longitude} pair. Free coords for ~150
top-tier clubs without any HTTP call.

Match to clubs via the 'sofascore-id' alias persisted by scripts/07.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("geo_from_cache")

TEAMS_DIR = ROOT / "data" / "raw" / "sofascore" / "teams"


def ensure_columns(conn) -> None:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(clubs)").fetchall()}
    if "lat" not in cols:
        conn.execute("ALTER TABLE clubs ADD COLUMN lat REAL")
        log.info("added column lat")
    if "lng" not in cols:
        conn.execute("ALTER TABLE clubs ADD COLUMN lng REAL")
        log.info("added column lng")


def build_coord_map() -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for f in TEAMS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        # Cached payload is the raw API response: {"team": {...}, "pregameForm": ...}.
        # Older calls returned just the team object, so accept either shape.
        team = data.get("team") if "team" in data else data
        venue = (team or {}).get("venue") or {}
        coords = venue.get("venueCoordinates") or {}
        lat = coords.get("latitude")
        lng = coords.get("longitude")
        tid = (team or {}).get("id")
        if tid and isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            out[str(tid)] = (float(lat), float(lng))
    return out


def run() -> None:
    coords = build_coord_map()
    log.info("found coords for %d sofascore teams in cache", len(coords))

    with connect() as conn:
        ensure_columns(conn)
        rows = conn.execute(
            """
            SELECT c.id, a.alias AS sofascore_id
            FROM clubs c
            JOIN club_aliases a ON a.club_id = c.id
            WHERE a.source = 'sofascore-id' AND c.lat IS NULL
            """
        ).fetchall()

        updated = 0
        for r in rows:
            ll = coords.get(r["sofascore_id"])
            if not ll:
                continue
            lat, lng = ll
            conn.execute(
                "UPDATE clubs SET lat = ?, lng = ? WHERE id = ?",
                (lat, lng, r["id"]),
            )
            updated += 1
        conn.commit()

        total_with_coords = conn.execute(
            "SELECT COUNT(*) FROM clubs WHERE lat IS NOT NULL"
        ).fetchone()[0]
        log.info("updated %d clubs from sofascore cache", updated)
        log.info("total clubs with coords now: %d", total_with_coords)


if __name__ == "__main__":
    run()
