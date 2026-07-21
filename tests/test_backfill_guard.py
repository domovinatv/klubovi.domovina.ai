"""The namesake guard in src/backfill.py.

Reproduces run_id 471 — club 888 `NK Mladost (Z)` (really Zabok) — and asserts
the two holes that let it through are closed:

  1. the old guard was `if _PAREN_RE.search(name) and club_row.get("county")`,
     so a club with an empty county skipped verification entirely; 31 clubs
     are in exactly that state
  2. even with a county it only rejected five hardcoded pro-club cities, so
     Ždralovi/Bjelovar sailed past

No network: the Firecrawl client is a stub that replays the URLs recorded in
`backfill_runs.source_urls` for that run.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src import backfill
from src.backfill import backfill_club, namesake_candidates, place_evidence
from tests.conftest import insert_club

# The three URLs Firecrawl actually returned for run_id 471, in order. The
# first is a different club's site; the second is the correct one.
RUN_471_RESULTS = [
    {"url": "https://mladost-zdralovi.hr/kontakt/"},
    {"url": "https://nk-mladost-zabok.hr/kontakt/"},
    {"url": "https://semafor.hns.family/en/clubs/1083/nk-mladost/?cid=102010625"},
]

ZDRALOVI_EXTRACT = {
    "email": "info@nk-mladost.hr",
    "phone": "+385 91 5210 944",
    "address": "Daruvarska ul. 42, Ždralovi, 43000 Bjelovar",
    "website": "https://mladost-zdralovi.hr/",
    "facebook_url": "https://www.facebook.com/nkmladostzdralovi",
    "founded_year": 1975,
    "city": "Bjelovar",
}


class StubFirecrawl:
    """Records calls so a test can assert we never even scraped."""

    def __init__(self, results, extract):
        self.results = results
        self.extract = extract
        self.searches: list[str] = []
        self.scrapes: list[str] = []

    def search(self, query, limit=5):
        self.searches.append(query)
        return self.results[:limit]

    def scrape_json(self, url, schema, prompt):
        self.scrapes.append(url)
        return dict(self.extract)


@pytest.fixture
def conn(db_path: Path):
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def make_club(conn, **overrides) -> dict:
    fields = dict(
        id=888, slug="mladost-z", canonical_name="NK Mladost (Z)",
        city=None, county="",
    )
    fields.update(overrides)
    insert_club(conn, **fields)
    conn.commit()
    return dict(conn.execute("SELECT * FROM clubs WHERE id = ?", (fields["id"],)).fetchone())


class TestParenNameWithoutCounty:
    """The exact hole: no county meant no guard at all."""

    def test_empty_county_no_longer_skips_verification(self, conn, monkeypatch):
        monkeypatch.setattr(backfill, "team_county_from_cache", lambda *a, **k: None)
        club = make_club(conn)
        # Single result, so the ambiguity guard cannot be what saves us —
        # this isolates the place check.
        client = StubFirecrawl(RUN_471_RESULTS[:1], ZDRALOVI_EXTRACT)

        result = backfill_club(conn, client, club)

        assert result["status"] == "place-mismatch"
        assert result["fields"] == []

    def test_nothing_is_written_to_the_club_row(self, conn, monkeypatch):
        monkeypatch.setattr(backfill, "team_county_from_cache", lambda *a, **k: None)
        club = make_club(conn)
        backfill_club(conn, StubFirecrawl(RUN_471_RESULTS[:1], ZDRALOVI_EXTRACT), club)
        conn.commit()

        row = dict(conn.execute("SELECT * FROM clubs WHERE id = 888").fetchone())
        assert row["phone"] is None
        assert row["email"] is None
        assert row["website"] is None
        assert row["city"] is None, "city is what poisoned the geo verification"

    def test_rejection_is_still_audited(self, conn, monkeypatch):
        monkeypatch.setattr(backfill, "team_county_from_cache", lambda *a, **k: None)
        club = make_club(conn)
        backfill_club(conn, StubFirecrawl(RUN_471_RESULTS[:1], ZDRALOVI_EXTRACT), club)
        conn.commit()
        runs = conn.execute("SELECT fields_filled FROM backfill_runs WHERE club_id=888").fetchall()
        assert len(runs) == 1 and runs[0]["fields_filled"] == "[]"


class TestCountyFallback:
    def test_county_is_resolved_from_hrnogomet_county_id(self, conn, monkeypatch):
        # The feed gives `countyId` even when clubs.county is empty; the guard
        # has to use it rather than give up.
        monkeypatch.setattr(backfill, "team_county_from_cache",
                            lambda *a, **k: "Krapinsko-zagorska županija")
        club = make_club(conn)
        conn.execute("INSERT INTO club_aliases (club_id, alias, source) VALUES (?,?,?)",
                     (888, "1035", "hrnogomet-id"))
        conn.commit()

        assert backfill.resolve_county(conn, club) == "Krapinsko-zagorska županija"

    def test_wrong_county_extraction_is_rejected(self, conn, monkeypatch):
        monkeypatch.setattr(backfill, "team_county_from_cache",
                            lambda *a, **k: "Krapinsko-zagorska županija")
        club = make_club(conn)
        conn.execute("INSERT INTO club_aliases (club_id, alias, source) VALUES (?,?,?)",
                     (888, "1035", "hrnogomet-id"))
        conn.commit()
        result = backfill_club(conn, StubFirecrawl(RUN_471_RESULTS[:1], ZDRALOVI_EXTRACT), club)
        assert result["status"] == "place-mismatch"

    def test_right_county_extraction_is_accepted(self, conn, monkeypatch):
        monkeypatch.setattr(backfill, "team_county_from_cache",
                            lambda *a, **k: "Krapinsko-zagorska županija")
        club = make_club(conn)
        conn.execute("INSERT INTO club_aliases (club_id, alias, source) VALUES (?,?,?)",
                     (888, "1035", "hrnogomet-id"))
        conn.commit()
        zabok = dict(ZDRALOVI_EXTRACT,
                     address="Ulica Matije Gupca 10, 49210 Zabok",
                     city="Zabok", website="https://nk-mladost-zabok.hr/")
        result = backfill_club(
            conn, StubFirecrawl([{"url": "https://nk-mladost-zabok.hr/kontakt/"}], zabok), club)
        assert result["status"] == "ok"
        assert "phone" in result["fields"]


class TestAmbiguousNamesakes:
    def test_two_plausible_domains_write_nothing(self, conn, monkeypatch):
        monkeypatch.setattr(backfill, "team_county_from_cache", lambda *a, **k: None)
        club = make_club(conn)
        client = StubFirecrawl(RUN_471_RESULTS, ZDRALOVI_EXTRACT)

        result = backfill_club(conn, client, club)

        assert result["status"] == "ambiguous"
        assert set(result["candidates"]) == {"mladost-zdralovi.hr", "nk-mladost-zabok.hr"}
        assert client.scrapes == [], "must not spend a scrape credit on an unresolvable club"

    def test_unambiguous_name_is_not_gated(self):
        # No paren disambiguator -> the club name itself is the answer.
        assert namesake_candidates(RUN_471_RESULTS, "NK Mladost Ždralovi") == []

    def test_single_candidate_domain_is_not_ambiguous(self):
        results = [{"url": "https://mladost-zdralovi.hr/kontakt/"},
                   {"url": "https://mladost-zdralovi.hr/o-klubu/"}]
        assert namesake_candidates(results, "NK Mladost (Z)") == []


class TestPlaceEvidence:
    def test_specific_city_beats_a_matching_county(self):
        # Ždralovi and Zabok share a county in neither direction, but the
        # point stands: when we know the city, the county must not rescue a
        # source that names a different town.
        club = {"canonical_name": "NK Mladost (Z)", "city": "Zabok",
                "registry_naziv": None}
        ok, why = place_evidence(club, "Krapinsko-zagorska županija",
                                 "https://mladost-zdralovi.hr/kontakt/",
                                 {"address": "Daruvarska ul. 42, Ždralovi, 43000 Bjelovar"})
        assert not ok and "expected one of" in why

    def test_registry_place_counts_as_a_specific_signal(self):
        club = {"canonical_name": "NK Mladost (Z)", "city": None,
                "registry_naziv": 'Nogometni klub "Mladost" Zabok'}
        ok, _ = place_evidence(club, "", "https://nk-mladost-zabok.hr/",
                               {"address": "Ulica Matije Gupca 10, 49210 Zabok"})
        assert ok

    def test_county_adjective_matches_town_by_prefix(self):
        # Fallback tier: no postcode in the address, but "Bjelovarsko-
        # bilogorska" shares a stem with "Bjelovar".
        club = {"canonical_name": "NK Mladost (NP)", "city": None, "registry_naziv": None}
        ok, why = place_evidence(club, "Bjelovarsko-bilogorska županija",
                                 "https://example.hr/", {"address": "Ulica Kralja Tomislava, Bjelovar"})
        assert ok and why.startswith("county match")

    def test_postcode_settles_a_county_whose_name_shares_no_stem(self):
        # The case the prefix heuristic cannot reach: Zabok is in
        # Krapinsko-zagorska, and the two words have nothing in common.
        club = {"canonical_name": "NK Mladost (Z)", "city": None, "registry_naziv": None}
        ok, why = place_evidence(club, "Krapinsko-zagorska županija",
                                 "https://nk-mladost-zabok.hr/",
                                 {"address": "Ulica Matije Gupca 10, 49210 Zabok"})
        assert ok and "postcode" in why

    def test_postcode_from_another_county_is_rejected(self):
        # Same club, the Ždralovi address that actually leaked. 43000 is
        # Bjelovarsko-bilogorska, so this cannot be our Zabok club.
        club = {"canonical_name": "NK Mladost (Z)", "city": None, "registry_naziv": None}
        ok, why = place_evidence(club, "Krapinsko-zagorska županija",
                                 "https://mladost-zdralovi.hr/",
                                 {"address": "Daruvarska ul. 42, Ždralovi, 43000 Bjelovar"})
        assert not ok and "postcode implies" in why

    def test_zagreb_city_and_county_are_compatible(self):
        club = {"canonical_name": "NK Sloga (V)", "city": None, "registry_naziv": None}
        ok, _ = place_evidence(club, "Zagrebačka županija", "https://example.hr/",
                               {"address": "Ilica 1, 10000 Zagreb"})
        assert ok

    def test_no_signal_at_all_is_a_rejection(self):
        club = {"canonical_name": "NK Mladost (Z)", "city": None, "registry_naziv": None}
        ok, why = place_evidence(club, "", "https://mladost-zdralovi.hr/",
                                 {"address": "Daruvarska ul. 42, Ždralovi"})
        assert not ok and "no city, registry or county signal" in why

    def test_source_naming_no_place_is_a_rejection(self):
        club = {"canonical_name": "NK Mladost (Z)", "city": "Zabok", "registry_naziv": None}
        ok, why = place_evidence(club, "", "https://x.hr/", {"address": None, "city": None})
        assert not ok
