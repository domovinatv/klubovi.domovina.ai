"""One-shot export of the whole clubs DB to ~/Desktop as a single CSV.

Opens SQLite in read-only mode (file:...?mode=ro) so it can run in parallel
with an active ingest/backfill writer without locking the database.

Output: ~/Desktop/hrvatski-nogometni-klubovi-YYYY-MM-DD.csv

Each row is one club. All `clubs` columns are included verbatim, plus two
denormalized helpers:

  leagues   semicolon-separated "T{tier}: {league_name} ({season})"
  aliases   semicolon-separated "{alias} [{source}]" (excluding numeric IDs)
"""
from __future__ import annotations

import csv
import logging
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "clubs.db"
DESKTOP = Path.home() / "Desktop"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("export_csv")


def ro_connect(db_path: Path) -> sqlite3.Connection:
    """Open SQLite read-only so we don't block any concurrent writer."""
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def run() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found: {DB_PATH}")

    out_path = DESKTOP / f"hrvatski-nogometni-klubovi-{date.today().isoformat()}.csv"

    with ro_connect(DB_PATH) as conn:
        # Discover columns so the script keeps working if we add more later.
        club_cols = [r["name"] for r in conn.execute("PRAGMA table_info(clubs)").fetchall()]
        clubs = [dict(r) for r in conn.execute(
            "SELECT * FROM clubs ORDER BY canonical_name"
        ).fetchall()]

        # Pre-fetch all leagues + seasons for all clubs in one pass — faster
        # than 901 individual queries.
        league_rows = conn.execute(
            """
            SELECT cs.club_id, l.tier, l.name AS league_name, cs.season
            FROM club_seasons cs
            JOIN leagues l ON l.id = cs.league_id
            ORDER BY l.tier, l.name
            """
        ).fetchall()
        leagues_by_club: dict[int, list[str]] = {}
        for r in league_rows:
            leagues_by_club.setdefault(r["club_id"], []).append(
                f"T{r['tier']}: {r['league_name']} ({r['season']})"
            )

        alias_rows = conn.execute(
            "SELECT club_id, alias, source FROM club_aliases "
            "WHERE source NOT LIKE '%-id'"
        ).fetchall()
        aliases_by_club: dict[int, list[str]] = {}
        for r in alias_rows:
            aliases_by_club.setdefault(r["club_id"], []).append(
                f"{r['alias']} [{r['source']}]"
            )

    columns = club_cols + ["leagues", "aliases"]
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for c in clubs:
            row = [c.get(col, "") if c.get(col) is not None else "" for col in club_cols]
            row.append("; ".join(leagues_by_club.get(c["id"], [])))
            row.append("; ".join(aliases_by_club.get(c["id"], [])))
            w.writerow(row)

    size_kb = out_path.stat().st_size / 1024
    log.info("wrote %d clubs (%d columns) -> %s  (%.1f KB)",
             len(clubs), len(columns), out_path, size_kb)


if __name__ == "__main__":
    run()
