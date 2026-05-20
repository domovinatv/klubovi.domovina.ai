#!/usr/bin/env python3
"""
Step 32 — Ingest OpenStreetMap football pitches + stadiums into clubs.db.

Pulls every Croatian football pitch (`leisure=pitch` + `sport=soccer`) and
every stadium (`leisure=stadium`) from the OSM Overpass API. Stores the
ground-truth geometry in two new tables, then matches each club to its
nearest pitch/stadium within 1500 m and writes `geo_truth_source` on the
club row so downstream consumers (karta-hrvatske export) can pick the
"closer-to-pitch" coordinate when Google + Nominatim disagree.

Idempotent: re-runs replace OSM rows by `osm_type:osm_id` PK and refresh
the match decisions on `clubs`. Safe to schedule.

Outputs:
  - pitches table:   id, osm_type, osm_id, name, geom_lat, geom_lng, source_tags
  - stadiums table:  id, osm_type, osm_id, name, geom_lat, geom_lng, source_tags
  - clubs.geo_truth_source:  'osm:google' | 'osm:nominatim' | 'unverified' | NULL
  - clubs.osm_pitch_id:      FK to pitches.id (when matched)

External dependency: requires httpx (already in pyproject deps).
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
import time
from pathlib import Path

try:
    import httpx
except ImportError:
    print("Install httpx first (uv add httpx or pip install httpx).", file=sys.stderr)
    sys.exit(1)

DB = Path(__file__).resolve().parent.parent / "data" / "clubs.db"
OVERPASS = "https://overpass-api.de/api/interpreter"

# Bounding box for the Republic of Croatia. Slight padding to capture edge
# cases (border-adjacent pitches mapped on the HR side of the line).
HR_BBOX = "42.3,13.4,46.6,19.5"

OVERPASS_QUERY = f"""
[out:json][timeout:90];
(
  way["leisure"="pitch"]["sport"~"soccer|football"]({HR_BBOX});
  relation["leisure"="pitch"]["sport"~"soccer|football"]({HR_BBOX});
  way["leisure"="stadium"]({HR_BBOX});
  relation["leisure"="stadium"]({HR_BBOX});
);
out center tags;
"""

# Match radius — clubs within this many metres of an OSM pitch get the
# tighter (= closer to pitch) of Nominatim / Google. 1500 m covers village-
# centroid vs actual-stadium discrepancies without picking up neighbouring
# villages' pitches.
MATCH_RADIUS_M = 1500.0

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pitches (
    id          INTEGER PRIMARY KEY,
    osm_type    TEXT NOT NULL,                  -- 'way' | 'relation'
    osm_id      INTEGER NOT NULL,
    name        TEXT,
    geom_lat    REAL NOT NULL,
    geom_lng    REAL NOT NULL,
    sport       TEXT,
    surface     TEXT,
    raw_tags    TEXT,                            -- JSON blob of all tags
    fetched_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(osm_type, osm_id)
);
CREATE INDEX IF NOT EXISTS idx_pitches_lat ON pitches(geom_lat);
CREATE INDEX IF NOT EXISTS idx_pitches_lng ON pitches(geom_lng);

CREATE TABLE IF NOT EXISTS stadiums (
    id          INTEGER PRIMARY KEY,
    osm_type    TEXT NOT NULL,
    osm_id      INTEGER NOT NULL,
    name        TEXT,
    geom_lat    REAL NOT NULL,
    geom_lng    REAL NOT NULL,
    capacity    INTEGER,
    raw_tags    TEXT,
    fetched_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(osm_type, osm_id)
);
CREATE INDEX IF NOT EXISTS idx_stadiums_lat ON stadiums(geom_lat);
CREATE INDEX IF NOT EXISTS idx_stadiums_lng ON stadiums(geom_lng);
"""

# Extra columns we add to `clubs` — guarded by PRAGMA so re-runs don't fail.
EXTRA_CLUB_COLS = [
    ("geo_truth_source", "TEXT"),
    ("osm_pitch_id", "INTEGER"),
    ("osm_pitch_distance_m", "INTEGER"),
]


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6_371_000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(clubs)").fetchall()}
    for col, ctype in EXTRA_CLUB_COLS:
        if col not in cols:
            conn.execute(f"ALTER TABLE clubs ADD COLUMN {col} {ctype}")
    conn.commit()


def fetch_overpass() -> dict:
    print(f"▸ Querying Overpass for HR football pitches + stadiums…")
    t0 = time.time()
    # Overpass returns 406 without a User-Agent; identify the script so
    # admins can rate-limit per app rather than blanket-block our IP.
    headers = {"User-Agent": "domovina.ai-clubs (info@domovina.ai)"}
    with httpx.Client(timeout=120.0, headers=headers) as c:
        r = c.post(OVERPASS, data={"data": OVERPASS_QUERY})
    r.raise_for_status()
    payload = r.json()
    print(f"  {len(payload['elements'])} elements in {time.time() - t0:.1f}s")
    return payload


def upsert_features(conn: sqlite3.Connection, payload: dict) -> tuple[int, int]:
    n_pitch = 0
    n_stadium = 0
    for el in payload["elements"]:
        tags = el.get("tags", {}) or {}
        name = tags.get("name")
        # `out center` produces a center{lat,lon} field for ways/relations
        # (which don't carry the geometry directly when we don't `out geom`).
        # Nodes would carry lat/lon at top level — Overpass never returns
        # bare nodes for our query so we don't have to handle that case.
        center = el.get("center") or {}
        lat = center.get("lat") or el.get("lat")
        lng = center.get("lon") or el.get("lon")
        if lat is None or lng is None:
            continue

        leisure = tags.get("leisure")
        sport = tags.get("sport", "")
        is_stadium = leisure == "stadium"
        is_soccer_pitch = leisure == "pitch" and ("soccer" in sport or "football" in sport)

        raw_tags_json = json.dumps(tags, ensure_ascii=False)

        if is_stadium:
            capacity_str = tags.get("capacity")
            try:
                capacity = int(capacity_str) if capacity_str else None
            except (TypeError, ValueError):
                capacity = None
            conn.execute(
                """INSERT INTO stadiums(osm_type, osm_id, name, geom_lat, geom_lng,
                                        capacity, raw_tags)
                   VALUES(?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(osm_type, osm_id) DO UPDATE SET
                     name=excluded.name, geom_lat=excluded.geom_lat,
                     geom_lng=excluded.geom_lng, capacity=excluded.capacity,
                     raw_tags=excluded.raw_tags, fetched_at=CURRENT_TIMESTAMP""",
                (el["type"], el["id"], name, lat, lng, capacity, raw_tags_json),
            )
            n_stadium += 1
        elif is_soccer_pitch:
            conn.execute(
                """INSERT INTO pitches(osm_type, osm_id, name, geom_lat, geom_lng,
                                       sport, surface, raw_tags)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(osm_type, osm_id) DO UPDATE SET
                     name=excluded.name, geom_lat=excluded.geom_lat,
                     geom_lng=excluded.geom_lng, sport=excluded.sport,
                     surface=excluded.surface, raw_tags=excluded.raw_tags,
                     fetched_at=CURRENT_TIMESTAMP""",
                (
                    el["type"],
                    el["id"],
                    name,
                    lat,
                    lng,
                    sport,
                    tags.get("surface"),
                    raw_tags_json,
                ),
            )
            n_pitch += 1
    conn.commit()
    print(f"  upserted {n_pitch} pitches + {n_stadium} stadiums")
    return n_pitch, n_stadium


def verify_clubs(conn: sqlite3.Connection) -> dict[str, int]:
    """For each club with lat_google present, pick the candidate (nominatim
    vs google) closer to the nearest OSM pitch (within MATCH_RADIUS_M).
    Write geo_truth_source + osm_pitch_id + osm_pitch_distance_m."""
    pitches = conn.execute("SELECT id, geom_lat, geom_lng FROM pitches").fetchall()
    print(f"▸ Verifying clubs against {len(pitches)} pitches…")

    def nearest_pitch(lat: float, lng: float) -> tuple[int, float] | None:
        # Coarse pre-filter via ~lat/lng box (≈0.025° ≈ 2.7 km) then exact
        # haversine. Pitches table has 1500-ish rows so even O(n) sweep is
        # fine, but the box keeps it constant-time over HR.
        delta = 0.025
        best_id = None
        best_d = math.inf
        for pid, plat, plng in pitches:
            if abs(plat - lat) > delta or abs(plng - lng) > delta:
                continue
            d = haversine_m(lat, lng, plat, plng)
            if d < best_d:
                best_d = d
                best_id = pid
        if best_id is None:
            return None
        return best_id, best_d

    stats = {"osm:google": 0, "osm:nominatim": 0, "osm:tie": 0, "unverified": 0}
    rows = conn.execute(
        "SELECT id, lat, lng, lat_google, lng_google FROM clubs "
        "WHERE lat IS NOT NULL AND lng IS NOT NULL"
    ).fetchall()
    for cid, lat_n, lng_n, lat_g, lng_g in rows:
        if lat_g is None or lng_g is None:
            # Only one candidate; check it against pitches but don't pick a winner.
            n = nearest_pitch(lat_n, lng_n)
            if n and n[1] <= MATCH_RADIUS_M:
                conn.execute(
                    "UPDATE clubs SET geo_truth_source=?, osm_pitch_id=?, "
                    "osm_pitch_distance_m=? WHERE id=?",
                    ("osm:nominatim", n[0], int(round(n[1])), cid),
                )
                stats["osm:nominatim"] += 1
            else:
                conn.execute(
                    "UPDATE clubs SET geo_truth_source=?, osm_pitch_id=NULL, "
                    "osm_pitch_distance_m=NULL WHERE id=?",
                    ("unverified", cid),
                )
                stats["unverified"] += 1
            continue

        nn = nearest_pitch(lat_n, lng_n)
        ng = nearest_pitch(lat_g, lng_g)
        cand: list[tuple[str, int, float]] = []
        if nn and nn[1] <= MATCH_RADIUS_M:
            cand.append(("osm:nominatim", nn[0], nn[1]))
        if ng and ng[1] <= MATCH_RADIUS_M:
            cand.append(("osm:google", ng[0], ng[1]))
        if not cand:
            conn.execute(
                "UPDATE clubs SET geo_truth_source=?, osm_pitch_id=NULL, "
                "osm_pitch_distance_m=NULL WHERE id=?",
                ("unverified", cid),
            )
            stats["unverified"] += 1
            continue
        cand.sort(key=lambda c: c[2])
        # If both candidates lock onto the same OSM pitch and the distance
        # delta is small (<50 m), treat as tie — both effectively correct.
        if (
            len(cand) == 2
            and cand[0][1] == cand[1][1]
            and abs(cand[0][2] - cand[1][2]) < 50.0
        ):
            chosen = "osm:tie"
            pitch_id = cand[0][1]
            dist = cand[0][2]
        else:
            chosen = cand[0][0]
            pitch_id = cand[0][1]
            dist = cand[0][2]
        conn.execute(
            "UPDATE clubs SET geo_truth_source=?, osm_pitch_id=?, "
            "osm_pitch_distance_m=? WHERE id=?",
            (chosen, pitch_id, int(round(dist)), cid),
        )
        stats[chosen] += 1
    conn.commit()
    return stats


def main() -> None:
    if not DB.exists():
        raise SystemExit(f"Missing {DB}")
    conn = sqlite3.connect(DB)
    ensure_schema(conn)

    payload = fetch_overpass()
    n_pitch, n_stadium = upsert_features(conn, payload)

    stats = verify_clubs(conn)
    total = sum(stats.values())
    print(f"▸ Club geo_truth_source distribution (n={total}):")
    for k, v in sorted(stats.items(), key=lambda kv: -kv[1]):
        print(f"    {k:18s} {v:4d}  ({100 * v / total:.1f}%)")

    conn.close()
    print(f"✓ Done. Pitches in DB: {n_pitch}, stadiums: {n_stadium}.")


if __name__ == "__main__":
    main()
