from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "clubs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS clubs (
  id               INTEGER PRIMARY KEY,
  canonical_name   TEXT NOT NULL,
  slug             TEXT UNIQUE NOT NULL,
  short_name       TEXT,
  city             TEXT,
  county           TEXT,
  founded_year     INTEGER,
  stadium_name     TEXT,
  stadium_capacity INTEGER,
  website          TEXT,
  email            TEXT,
  phone            TEXT,
  phone_kind       TEXT,   -- 'mobile' | 'landline' | 'unknown' (see src/phones.py)
  phone_e164       TEXT,   -- +385...
  address          TEXT,
  fb_url           TEXT,
  ig_url           TEXT,
  x_url            TEXT,
  president        TEXT,
  lat              REAL,
  lng              REAL,
  notes            TEXT,
  created_at       TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at       TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS club_aliases (
  alias_id   INTEGER PRIMARY KEY,
  club_id    INTEGER NOT NULL REFERENCES clubs(id) ON DELETE CASCADE,
  alias      TEXT NOT NULL,
  source     TEXT,
  UNIQUE(alias, source)
);

CREATE TABLE IF NOT EXISTS leagues (
  id                       INTEGER PRIMARY KEY,
  name                     TEXT NOT NULL,
  tier                     INTEGER NOT NULL,
  parent_id                INTEGER REFERENCES leagues(id),
  county                   TEXT,
  sofascore_tournament_id  INTEGER UNIQUE
);

CREATE TABLE IF NOT EXISTS club_seasons (
  club_id    INTEGER NOT NULL REFERENCES clubs(id) ON DELETE CASCADE,
  league_id  INTEGER NOT NULL REFERENCES leagues(id),
  season     TEXT NOT NULL,
  source     TEXT NOT NULL,
  PRIMARY KEY (club_id, league_id, season)
);

CREATE TABLE IF NOT EXISTS backfill_runs (
  run_id         INTEGER PRIMARY KEY,
  club_id        INTEGER NOT NULL REFERENCES clubs(id) ON DELETE CASCADE,
  ran_at         TEXT DEFAULT CURRENT_TIMESTAMP,
  fields_filled  TEXT,
  source_urls    TEXT,
  raw_dump_path  TEXT
);

CREATE INDEX IF NOT EXISTS idx_clubs_canonical ON clubs(canonical_name);
CREATE INDEX IF NOT EXISTS idx_clubs_city ON clubs(city);
CREATE INDEX IF NOT EXISTS idx_aliases_alias ON club_aliases(alias);
"""


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def upsert_league(
    conn: sqlite3.Connection,
    name: str,
    tier: int,
    sofascore_tournament_id: int | None = None,
    parent_id: int | None = None,
    county: str | None = None,
) -> int:
    if sofascore_tournament_id is not None:
        row = conn.execute(
            "SELECT id FROM leagues WHERE sofascore_tournament_id = ?",
            (sofascore_tournament_id,),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE leagues SET name=?, tier=?, parent_id=?, county=? WHERE id=?",
                (name, tier, parent_id, county, row["id"]),
            )
            return row["id"]
    cur = conn.execute(
        "INSERT INTO leagues (name, tier, parent_id, county, sofascore_tournament_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (name, tier, parent_id, county, sofascore_tournament_id),
    )
    return cur.lastrowid


def upsert_club(conn: sqlite3.Connection, slug: str, canonical_name: str, **fields) -> int:
    cols = ["slug", "canonical_name", *fields.keys()]
    vals = [slug, canonical_name, *fields.values()]
    placeholders = ", ".join(["?"] * len(cols))
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "slug")
    sql = (
        f"INSERT INTO clubs ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(slug) DO UPDATE SET {updates}, updated_at=CURRENT_TIMESTAMP "
        "RETURNING id"
    )
    row = conn.execute(sql, vals).fetchone()
    return row["id"]


def add_alias(conn: sqlite3.Connection, club_id: int, alias: str, source: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO club_aliases (club_id, alias, source) VALUES (?, ?, ?)",
        (club_id, alias, source),
    )


def link_club_season(
    conn: sqlite3.Connection, club_id: int, league_id: int, season: str, source: str
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO club_seasons (club_id, league_id, season, source) "
        "VALUES (?, ?, ?, ?)",
        (club_id, league_id, season, source),
    )
