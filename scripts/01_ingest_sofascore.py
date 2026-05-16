"""Ingest Croatian football clubs from SofaScore for all tournament-covered tiers.

Tournaments listed in TOURNAMENTS are processed top-down. For each tournament we
grab the current season, fetch its teams, then fetch each team's detail page to
also capture stadium + founding year. Everything is upserted into clubs +
club_seasons; raw JSON lands in data/raw/sofascore/ for reproducibility.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import (  # noqa: E402
    add_alias,
    connect,
    init_db,
    link_club_season,
    upsert_club,
    upsert_league,
)
from src.normalize import short_name, slugify  # noqa: E402
from src.sofascore import SofaScoreClient  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("ingest_sofascore")

# (name, tier, tournament_id). Tournament IDs verified via the Croatia category
# listing (/category/14/unique-tournaments). The legacy "3. HNL" groups
# (15962-15965, last covered 2021/22) are intentionally omitted: post-reform
# structure replaces them with 2. NL (tier 3) and the 3. NL regional groups
# (tier 4).
TOURNAMENTS: list[tuple[str, int, int]] = [
    ("SuperSport HNL", 1, 170),
    ("1. NL", 2, 724),
    ("2. NL", 3, 19122),
    ("3. NL - Sjever", 4, 19051),
    ("3. NL - Istok", 4, 19114),
    ("3. NL - Zapad", 4, 19115),
    ("3. NL - Centar", 4, 19132),
    ("3. NL - Jug", 4, 19124),
]


def founding_year(ts: int | None) -> int | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).year
    except (OSError, OverflowError, ValueError):
        return None


def ingest_team(conn, client, league_id: int, season_label: str, team_meta: dict) -> None:
    team_id = team_meta.get("id")
    name = team_meta.get("name") or team_meta.get("shortName") or ""
    if not team_id or not name:
        log.warning("skipping team with missing id/name: %r", team_meta)
        return

    detail = client.team(team_id)
    venue = detail.get("venue") or {}
    city = (venue.get("city") or {}).get("name")
    short = detail.get("shortName") or short_name(name)
    slug = slugify(name, city)

    club_id = upsert_club(
        conn,
        slug=slug,
        canonical_name=name,
        short_name=short,
        city=city,
        founded_year=founding_year(detail.get("foundationDateTimestamp")),
        stadium_name=venue.get("name"),
        stadium_capacity=venue.get("capacity"),
    )
    add_alias(conn, club_id, name, "sofascore")
    if short and short != name:
        add_alias(conn, club_id, short, "sofascore")
    link_club_season(conn, club_id, league_id, season_label, "sofascore")
    log.debug("upsert %s -> club_id=%s", slug, club_id)


def run() -> None:
    init_db()
    with connect() as conn, SofaScoreClient() as client:
        for tournament_name, tier, tournament_id in TOURNAMENTS:
            log.info("=== %s (tier %d, id=%d) ===", tournament_name, tier, tournament_id)
            season = client.current_season(tournament_id)
            if not season:
                log.warning("no seasons for %s", tournament_name)
                continue
            season_label = season.get("year") or season.get("name") or str(season["id"])
            league_id = upsert_league(
                conn,
                name=tournament_name,
                tier=tier,
                sofascore_tournament_id=tournament_id,
            )
            teams = client.teams(tournament_id, season["id"])
            log.info("season=%s teams=%d", season_label, len(teams))
            for t in teams:
                ingest_team(conn, client, league_id, season_label, t)
            conn.commit()

        total = conn.execute("SELECT COUNT(*) FROM clubs").fetchone()[0]
        log.info("done. clubs in db: %d", total)


if __name__ == "__main__":
    run()
