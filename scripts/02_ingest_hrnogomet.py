"""Ingest county-level (amateur) leagues from hrnogomet.hr.

SofaScore already covers HNL → 3. NL (tiers 1-4); this script focuses on what
SofaScore doesn't have:

  * "4. Nogometna Liga" (the regional inter-county league below 3. NL) -> tier 5
  * All 21 Croatian counties' adult senior men's leagues:
      1. ŽNL -> tier 6
      2. ŽNL -> tier 7
      3. ŽNL -> tier 8

Per-league filtering: skip cups (isCup=1), veterans, youth, women, and obvious
tournament/cup names. Tier is inferred from the league name.
"""
from __future__ import annotations

import logging
import re
import sys
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
from src.hrnogomet import HRNogometClient  # noqa: E402
from src.normalize import short_name, slugify  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("ingest_hrnogomet")

# Adult senior tournament names below 3. NL we want from hrnogomet.
# Top tiers (HNL through 3. NL) are already in DB from SofaScore — skip them
# here to avoid noisy duplicates with worse metadata (no city/stadium).
NATIONAL_ENTITY_TIERS = {
    "4. Nogometna Liga": 5,
}

# Per-league exclusion: any of these substrings in the (lowered) league name
# means "skip" — cups, youth, women, futsal, veterans, tournaments.
LEAGUE_SKIP_RE = re.compile(
    r"\b(kup|cup|trofej|trophy|veteran|mladež|mladez|žene|zene|"
    r"futsal|juniori|kadeti|pioniri|limači|limaci|"
    r"u\d{1,2}|turniri|prijateljske|league\s+s\d)\b",
    re.IGNORECASE,
)

ZNL_RE = re.compile(r"^\s*(\d)\s*\.\s*ŽNL", re.IGNORECASE)


def infer_county_tier(league_name: str) -> int | None:
    """Map a county league name to a tier (6/7/8) or None to skip."""
    m = ZNL_RE.search(league_name)
    if m:
        rank = int(m.group(1))
        return {1: 6, 2: 7, 3: 8, 4: 9}.get(rank, 99)
    lower = league_name.lower()
    if "premier" in lower or "elitna" in lower or "1. zagreba" in lower or lower.startswith("j1"):
        return 6
    if "2. zagreba" in lower:
        return 7
    return None  # unknown shape => skip rather than mislabel


def keep_league(league: dict, county_entity: bool) -> tuple[bool, int | None, str]:
    """Decide whether to ingest a league and return (keep, tier, reason)."""
    name = league.get("name", "")
    if league.get("isCup"):
        return False, None, "isCup=1"
    if league.get("hidden"):
        return False, None, "hidden"
    if LEAGUE_SKIP_RE.search(name):
        return False, None, "skip-pattern"
    if not county_entity:
        return False, None, "national-skipped"
    tier = infer_county_tier(name)
    if tier is None:
        return False, None, f"untiered:{name!r}"
    return True, tier, "ok"


def ingest_league(
    conn, client: HRNogometClient, league_id_db: int, season_label: str, league_short: str
) -> int:
    try:
        payload = client.team_standings(league_short)
    except RuntimeError as e:
        log.warning("standings failed for %s: %s", league_short, e)
        return 0
    teams = payload.get("teamStandings", []) or []
    for t in teams:
        name = t.get("teamName")
        team_id = t.get("teamId")
        if not name or not team_id:
            continue
        slug = slugify(name)  # no city info from hrnogomet standings
        club_id = upsert_club(
            conn,
            slug=slug,
            canonical_name=name,
            short_name=short_name(name),
        )
        add_alias(conn, club_id, name, "hrnogomet")
        # Store hrnogomet's stable teamId as a typed alias for later joins.
        add_alias(conn, club_id, str(team_id), "hrnogomet-id")
        link_club_season(conn, club_id, league_id_db, season_label, "hrnogomet")
    return len(teams)


def run() -> None:
    init_db()
    summary: dict[str, int] = {"counties": 0, "leagues_ingested": 0, "teams": 0, "skipped": 0}
    with connect() as conn, HRNogometClient() as client:
        county_data = client.county_leagues()
        for entity in county_data:
            entity_name = entity["name"]
            priority = entity.get("priority", 0)
            county_entity = priority == 50
            national_tier = NATIONAL_ENTITY_TIERS.get(entity_name)
            if not county_entity and not national_tier:
                continue

            log.info("=== %s [%s] %d leagues ===",
                     entity_name, entity.get("shortName"), len(entity["leagues"]))
            summary["counties"] += 1

            for league in entity["leagues"]:
                if national_tier is not None:
                    if league.get("isCup") or LEAGUE_SKIP_RE.search(league.get("name", "")):
                        summary["skipped"] += 1
                        continue
                    tier = national_tier
                else:
                    keep, tier, reason = keep_league(league, county_entity=True)
                    if not keep:
                        log.debug("skip %s: %s", league.get("name"), reason)
                        summary["skipped"] += 1
                        continue

                league_db_id = upsert_league(
                    conn,
                    name=f"{league['name']} ({entity['shortName']})"
                    if county_entity
                    else league["name"],
                    tier=tier,
                    county=entity_name if county_entity else None,
                )
                # We don't know the season label from the league record alone;
                # use the seasonId verbatim — good enough as a tag.
                season_label = f"hrnogomet-season-{league.get('seasonId')}"
                count = ingest_league(
                    conn, client, league_db_id, season_label, league["shortname"]
                )
                summary["leagues_ingested"] += 1
                summary["teams"] += count
                log.info("  %-30s tier=%d teams=%d", league["name"], tier, count)
                conn.commit()

        total_clubs = conn.execute("SELECT COUNT(*) FROM clubs").fetchone()[0]
        log.info("done. summary=%s total_clubs=%d", summary, total_clubs)


if __name__ == "__main__":
    run()
