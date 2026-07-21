"""Shared fixtures. Everything here runs against a synthetic SQLite file in
tmp_path — never against data/clubs.db — and nothing touches the network."""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import SCHEMA  # noqa: E402

# Columns added by later migrations that src.db.SCHEMA does not declare.
# The real DB has them; the synthetic one must too or the scoring signals
# silently read nothing.
EXTRA_COLUMNS = (
    "oib TEXT", "udruga_id TEXT", "president_role TEXT", "registry_status TEXT",
    "registry_naziv TEXT", "registry_url TEXT", "geo_source TEXT",
    "geo_truth_source TEXT",
)


def load_script(name: str):
    """Import a `scripts/NN_name.py` module — the leading digit makes them
    invalid identifiers, so a normal import statement will not do."""
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Empty synthetic DB with the production schema."""
    path = tmp_path / "clubs.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    for col in EXTRA_COLUMNS:
        conn.execute(f"ALTER TABLE clubs ADD COLUMN {col}")
    conn.commit()
    conn.close()
    return path


def insert_club(conn: sqlite3.Connection, **fields) -> int:
    cols = ", ".join(fields)
    marks = ", ".join("?" * len(fields))
    cur = conn.execute(f"INSERT INTO clubs ({cols}) VALUES ({marks})", list(fields.values()))
    return cur.lastrowid


# The exact leak from the report: six clubs, one contact block. Club 26 is the
# real owner — its city spells the domain and Registar udruga agrees — and the
# other five inherited everything from it because their hrnogomet names are
# `NK Mladost (X)` with no city attached.
ZDRALOVI_COHORT = [
    dict(id=26, slug="mladost-zdralovi", canonical_name="NK Mladost Ždralovi",
         city="Ždralovi", county="", phone="+385 91 5210 944",
         phone_kind="mobile", phone_e164="+385915210944",
         email="info@nk-mladost.hr", website="https://mladost-zdralovi.hr/",
         fb_url="https://www.facebook.com/nkmladostzdralovi",
         address="Daruvarska ul. 42, Ždralovi, 43000 Bjelovar",
         registry_naziv='Nogometni klub "Mladost" Ždralovi',
         semafor_url="https://semafor.hns.family/klubovi/1083",
         sofascore_url="https://www.sofascore.com/team/football/-/1",
         lat=45.9, lng=16.85, geo_source="both"),
]
for _sid, _tag in ((224, "O"), (416, "NP"), (804, "SM"), (853, "F"), (888, "Z")):
    ZDRALOVI_COHORT.append(dict(
        id=_sid, slug=f"mladost-{_tag.lower()}", canonical_name=f"NK Mladost ({_tag})",
        city="Bjelovar", county="", phone="+385 91 5210 944",
        phone_kind="mobile", phone_e164="+385915210944",
        email="info@nk-mladost.hr", website="https://mladost-zdralovi.hr/",
        fb_url="https://www.facebook.com/nkmladostzdralovi",
        address="Daruvarska ul. 42, Ždralovi, 43000 Bjelovar",
        registry_naziv='NOGOMETNI KLUB "MLADOST" PAVLOVCI',
        lat=45.9, lng=16.85, geo_source="both",
    ))


@pytest.fixture
def zdralovi_db(db_path: Path) -> Path:
    conn = sqlite3.connect(db_path)
    for club in ZDRALOVI_COHORT:
        insert_club(conn, **club)
    conn.commit()
    conn.close()
    return db_path
