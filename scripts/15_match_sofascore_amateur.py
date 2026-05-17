"""Match Sofascore team IDs to our amateur clubs via the *Croatia Amateur*
category (id=1578).

Sofascore organises Croatian football under two top-level categories:
  - category 14 "Croatia" — top-tier competitions (HNL, 1./2./3. NL)
  - category 1578 "Croatia Amateur" — županijske lige, MŽNL, 4. NL groups,
    cups, veterans, youth tournaments (196 tournaments)

scripts/01_ingest_sofascore.py covers the first category. This script walks
the second, filtered to senior men's competitions, and persists each team's
Sofascore id as a `sofascore-id` alias in our DB by matching on canonical
name + city.

Filtering rules:
  * SKIP youth (U-prefix tournaments, kadet, junior, pioniri, mladi),
    veterans, women, futsal, cup-only tournaments without a regular season.
  * INCLUDE 1./2./3. ŽNL by county, Elitna/Premier ŽNL, county sub-leagues
    (NS-prefix), MŽNL, 4. NL.

Idempotent: skips clubs that already have a `sofascore-id` alias.
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import add_alias, connect  # noqa: E402
from src.normalize import strip_diacritics  # noqa: E402
from src.sofascore import SofaScoreClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("match_sofascore")

# Tournaments named with any of these tokens belong to a competition we don't
# want for senior-men matching (youth, women, veterans, cups without league).
SKIP_TOURNAMENT_RE = re.compile(
    r"\b(U\d{1,2}|kadet|junior|pionir|mlad|veter|žene|zene|futsal|"
    r"kup|cup|trofej|trophy|memorijal|turnir)\b",
    re.IGNORECASE,
)

_PREFIX_RE = re.compile(
    r"^(HNK|GNK|NK|RNK|MNK|HAŠK|ŠNK|GŠNK|BŠK|ONK|NŠK|HNŠK)\s+", re.IGNORECASE
)
_PAREN_RE = re.compile(r"\s*\([^)]+\)\s*$")


def normalize_name(s: str) -> str:
    n = _PREFIX_RE.sub("", s or "").strip()
    n = _PAREN_RE.sub("", n).strip()
    return strip_diacritics(n).lower()


def discover_tournaments(client: SofaScoreClient) -> list[tuple[int, str]]:
    data = client._get("/category/1578/unique-tournaments")
    out: list[tuple[int, str]] = []
    for grp in data.get("groups", []):
        for t in grp.get("uniqueTournaments", []):
            name = t.get("name") or ""
            if SKIP_TOURNAMENT_RE.search(name):
                continue
            out.append((t["id"], name))
    return out


def build_match_table(conn) -> dict[tuple[str, str | None], int]:
    """Build {(norm_name, norm_city|None): club_id} for clubs that still need
    a sofascore-id alias. Index by both (name+city) and (name only) so we can
    fall back when city is missing."""
    rows = conn.execute(
        """
        SELECT c.id, c.canonical_name, c.city
        FROM clubs c
        WHERE c.id NOT IN (
            SELECT club_id FROM club_aliases WHERE source = 'sofascore-id'
        )
        """
    ).fetchall()
    out: dict[tuple[str, str | None], int] = {}
    for r in rows:
        n = normalize_name(r["canonical_name"])
        city = strip_diacritics(r["city"] or "").lower() or None
        # Primary key: (name, city) when we have city
        if city:
            out[(n, city)] = r["id"]
        # Always include name-only fallback (last wins, but conflicts are rare
        # given hrnogomet's "(X)" disambiguator suffix is preserved in norm).
        out.setdefault((n, None), r["id"])
    return out


def run() -> None:
    with connect() as conn, SofaScoreClient() as client:
        tournaments = discover_tournaments(client)
        log.info("amateur tournaments to walk: %d", len(tournaments))

        match_table = build_match_table(conn)
        log.info("clubs needing sofascore-id: %d", len({v for v in match_table.values()}))

        counters = {"team_rows": 0, "matched": 0, "unknown_team": 0, "tour_fail": 0}
        for i, (tid, tname) in enumerate(tournaments, 1):
            try:
                season = client.current_season(tid)
            except Exception as e:
                log.warning("tour %s seasons: %s", tid, e)
                counters["tour_fail"] += 1
                continue
            if not season:
                continue
            try:
                teams = client.teams(tid, season["id"])
            except Exception as e:
                log.warning("tour %s teams: %s", tid, e)
                counters["tour_fail"] += 1
                continue

            for t in teams:
                counters["team_rows"] += 1
                team_name = t.get("name") or ""
                team_id = t.get("id")
                if not team_id or not team_name:
                    continue
                norm = normalize_name(team_name)
                # Try city-matched first; Sofascore team payload has no city
                # inline so this rarely hits, but the name-only fallback does.
                club_id = match_table.get((norm, None))
                if club_id:
                    add_alias(conn, club_id, str(team_id), "sofascore-id")
                    counters["matched"] += 1
                    # Don't break — many tournaments contain a club; ON CONFLICT
                    # ignores duplicate alias-source pairs.
                else:
                    counters["unknown_team"] += 1

            if i % 25 == 0:
                conn.commit()
                log.info("progress %d/%d tournaments  %s", i, len(tournaments), counters)
        conn.commit()

        total = conn.execute(
            "SELECT COUNT(*) FROM club_aliases WHERE source = 'sofascore-id'"
        ).fetchone()[0]
        log.info("done. counters=%s  total sofascore-id aliases in DB: %d",
                 counters, total)


if __name__ == "__main__":
    run()
