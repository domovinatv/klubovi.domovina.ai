"""End-to-end detect -> repair, against a synthetic DB in tmp_path.

The invariants worth guarding are the destructive ones: a dry run must not
write, --execute must write exactly the planned NULLs and nothing else, and a
second --execute must be a no-op rather than a second round of damage.
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

import pytest

from tests.conftest import load_script

detect = load_script("60_detect_collisions.py")
quarantine = load_script("61_quarantine_leaks.py")

OWNER_ID = 26
ORPHAN_IDS = (224, 416, 804, 853, 888)


def run_cli(module, argv: list[str]):
    old = sys.argv
    sys.argv = ["script", *argv]
    try:
        module.main()
    finally:
        sys.argv = old


@pytest.fixture
def detected(zdralovi_db: Path, tmp_path: Path):
    """Run detection once; return (db, collisions.csv)."""
    csv_path = tmp_path / "collisions.csv"
    run_cli(detect, ["--db", str(zdralovi_db),
                     "--out-csv", str(csv_path),
                     "--out-json", str(tmp_path / "summary.json")])
    return zdralovi_db, csv_path


def quarantine_argv(db, csv_path, tmp_path, *extra):
    return ["--db", str(db), "--in-csv", str(csv_path),
            "--review-csv", str(tmp_path / "review.csv"),
            "--backup-dir", str(tmp_path / "backups"), *extra]


def club(db: Path, club_id: int) -> dict:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = dict(conn.execute("SELECT * FROM clubs WHERE id = ?", (club_id,)).fetchone())
    conn.close()
    return row


def table_exists(db: Path, name: str) -> bool:
    conn = sqlite3.connect(db)
    hit = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    conn.close()
    return hit is not None


class TestDetection:
    def test_writes_csv_without_touching_the_db(self, detected):
        db, csv_path = detected
        rows = list(csv.DictReader(csv_path.open()))
        assert rows
        # Every club still holds every value it started with.
        assert club(db, 888)["phone"] == "+385 91 5210 944"
        assert not table_exists(db, "data_repairs")

    def test_owner_and_orphans_are_labelled(self, detected):
        _, csv_path = detected
        rows = [r for r in csv.DictReader(csv_path.open()) if r["field"] == "website"]
        verdicts = {int(r["club_id"]): r["verdict"] for r in rows}
        assert verdicts[OWNER_ID] == "owner"
        assert all(verdicts[c] == "orphan" for c in ORPHAN_IDS)


class TestDryRun:
    def test_dry_run_changes_nothing(self, detected, tmp_path):
        db, csv_path = detected
        before = {cid: club(db, cid) for cid in (OWNER_ID, *ORPHAN_IDS)}
        run_cli(quarantine, quarantine_argv(db, csv_path, tmp_path))
        assert {cid: club(db, cid) for cid in (OWNER_ID, *ORPHAN_IDS)} == before
        assert not table_exists(db, "data_repairs")
        assert not table_exists(db, "backfill_queue")

    def test_dry_run_still_writes_the_review_queue(self, detected, tmp_path):
        db, csv_path = detected
        run_cli(quarantine, quarantine_argv(db, csv_path, tmp_path))
        assert (tmp_path / "review.csv").exists()


class TestExecute:
    @pytest.fixture
    def repaired(self, detected, tmp_path):
        db, csv_path = detected
        run_cli(quarantine, quarantine_argv(db, csv_path, tmp_path, "--execute"))
        return db, csv_path, tmp_path

    def test_orphans_are_nulled(self, repaired):
        db, _, _ = repaired
        for cid in ORPHAN_IDS:
            row = club(db, cid)
            assert row["phone"] is None
            assert row["phone_e164"] is None
            assert row["phone_kind"] is None
            assert row["email"] is None
            assert row["website"] is None
            assert row["fb_url"] is None
            assert row["address"] is None

    def test_owner_is_untouched(self, repaired):
        db, _, _ = repaired
        row = club(db, OWNER_ID)
        assert row["phone"] == "+385 91 5210 944"
        assert row["email"] == "info@nk-mladost.hr"
        assert row["website"] == "https://mladost-zdralovi.hr/"

    def test_geo_is_not_repaired_by_default(self, repaired):
        # Shared coordinates are often a genuinely shared pitch; nulling them
        # leaves a hole in the public map.
        db, _, _ = repaired
        assert all(club(db, cid)["lat"] is not None for cid in ORPHAN_IDS)

    def test_include_geo_opts_in(self, detected, tmp_path):
        db, csv_path = detected
        run_cli(quarantine, quarantine_argv(db, csv_path, tmp_path, "--execute", "--include-geo"))
        assert club(db, 888)["lat"] is None
        assert club(db, OWNER_ID)["lat"] is not None

    def test_every_null_is_reconstructible_from_data_repairs(self, repaired):
        db, _, _ = repaired
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM data_repairs WHERE club_id = 888")]
        conn.close()
        by_field = {r["field"]: r["old_value"] for r in rows}
        assert by_field["phone"] == "+385 91 5210 944"
        assert by_field["website"] == "https://mladost-zdralovi.hr/"
        assert all(r["new_value"] is None for r in rows)
        assert all("collision:" in r["reason"] for r in rows)

    def test_orphans_are_queued_for_rebackfill(self, repaired):
        db, _, _ = repaired
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        queued = {r["club_id"] for r in conn.execute("SELECT club_id FROM backfill_queue")}
        conn.close()
        assert set(ORPHAN_IDS) <= queued
        assert OWNER_ID not in queued

    def test_backup_is_written_before_any_change(self, repaired):
        db, _, tmp_path = repaired
        backups = list((tmp_path / "backups").glob("clubs-*.db"))
        assert len(backups) == 1
        # The snapshot must predate the repair — the orphan's phone is still
        # in it, which is what makes a rollback possible.
        conn = sqlite3.connect(backups[0])
        assert conn.execute("SELECT phone FROM clubs WHERE id=888").fetchone()[0] == \
            "+385 91 5210 944"
        conn.close()

    def test_no_registry_bundle_leak_when_oib_absent(self, repaired):
        # This fixture has no OIB, so president/registry columns must be
        # untouched even though registry_naziv fed the scoring.
        db, _, _ = repaired
        assert club(db, 888)["registry_naziv"] == 'NOGOMETNI KLUB "MLADOST" PAVLOVCI'


class TestIdempotency:
    def test_second_execute_is_a_no_op(self, detected, tmp_path):
        db, csv_path = detected
        run_cli(quarantine, quarantine_argv(db, csv_path, tmp_path, "--execute"))
        conn = sqlite3.connect(db)
        first = conn.execute("SELECT COUNT(*) FROM data_repairs").fetchone()[0]
        snapshot = conn.execute("SELECT * FROM clubs ORDER BY id").fetchall()
        conn.close()

        run_cli(quarantine, quarantine_argv(db, csv_path, tmp_path, "--execute",
                                            "--stamp", "second"))
        conn = sqlite3.connect(db)
        second = conn.execute("SELECT COUNT(*) FROM data_repairs").fetchone()[0]
        after = conn.execute("SELECT * FROM clubs ORDER BY id").fetchall()
        conn.close()

        assert first > 0
        assert second == first, "re-running logged phantom repairs for already-NULL fields"
        assert after == snapshot

    def test_rerunning_detection_after_repair_finds_no_collisions(self, detected, tmp_path):
        db, csv_path = detected
        run_cli(quarantine, quarantine_argv(db, csv_path, tmp_path, "--execute"))
        after_csv = tmp_path / "collisions2.csv"
        run_cli(detect, ["--db", str(db), "--out-csv", str(after_csv),
                         "--out-json", str(tmp_path / "s2.json")])
        remaining = [r for r in csv.DictReader(after_csv.open())
                     if r["field"] not in ("latlng",)]
        assert remaining == [], f"collisions survived the repair: {remaining[:3]}"
