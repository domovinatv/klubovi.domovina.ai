"""Normalization and owner-scoring — the deterministic core of detection."""
from __future__ import annotations

import pytest

from src.collisions import (
    FIELDS_BY_NAME,
    build_groups,
    club_tokens,
    norm_address,
    norm_domain,
    norm_email,
    norm_fb,
    norm_latlng,
    norm_oib,
    norm_phone,
    resolve_group,
)
from tests.conftest import ZDRALOVI_COHORT


class TestPhoneNormalization:
    @pytest.mark.parametrize("raw", [
        "+385 91 5210 944", "091 5210 944", "0915210944",
        "00385 91 5210 944", "+385915210944", "091/5210-944",
    ])
    def test_croatian_spellings_collapse_to_one_key(self, raw):
        # Six formats of one number must group together, or the collision
        # never surfaces and the SMS still goes to the wrong club.
        assert norm_phone(raw) == "+385915210944"

    def test_landline_with_area_code(self):
        assert norm_phone("01 3323 978") == "+38513323978"
        assert norm_phone("021-620-718") == "+38521620718"

    @pytest.mark.parametrize("raw", ["", None, "n/a", "12", "+49 30 123456789012"])
    def test_junk_is_not_grouped(self, raw):
        assert norm_phone(raw) is None


class TestDomainNormalization:
    @pytest.mark.parametrize("raw", [
        "https://mladost-zdralovi.hr/", "http://www.mladost-zdralovi.hr",
        "https://WWW.Mladost-Zdralovi.HR/kontakt/", "mladost-zdralovi.hr",
        "https://mladost-zdralovi.hr:443/kontakt?x=1#top",
    ])
    def test_spellings_collapse_to_registrable_domain(self, raw):
        assert norm_domain(raw) == "mladost-zdralovi.hr"

    def test_distinct_domains_stay_distinct(self):
        assert norm_domain("https://nk-mladost-zabok.hr/") != norm_domain(
            "https://mladost-zdralovi.hr/")


class TestOtherNormalizers:
    def test_email_lowercased(self):
        assert norm_email("  Info@NK-Mladost.HR ") == "info@nk-mladost.hr"
        assert norm_email("not-an-email") is None

    def test_fb_slug_forms_collapse(self):
        for url in ("https://facebook.com/NKMladostZdralovi",
                    "https://www.facebook.com/nkmladostzdralovi/",
                    "https://facebook.com/pg/nkmladostzdralovi/about"):
            assert norm_fb(url) == "nkmladostzdralovi"

    def test_fb_numeric_profile(self):
        assert norm_fb("https://facebook.com/profile.php?id=12345") == "profile:12345"

    def test_oib_requires_eleven_digits(self):
        assert norm_oib("65720969977") == "65720969977"
        assert norm_oib("HR 65720969977") == "65720969977"
        assert norm_oib("6572096") is None

    def test_address_folding(self):
        assert norm_address("Daruvarska ul. 42, Ždralovi, 43000 Bjelovar") == \
            norm_address("daruvarska ul 42  zdralovi 43000 bjelovar")

    def test_latlng_rounds_to_five_places(self):
        assert norm_latlng(45.90000004, 16.85) == norm_latlng(45.9, 16.85)
        assert norm_latlng(45.9, 16.85) != norm_latlng(45.91, 16.85)
        assert norm_latlng(None, 16.85) is None


class TestClubTokens:
    def test_generic_football_words_are_dropped(self):
        toks = club_tokens({"canonical_name": "NK Mladost Ždralovi", "city": "Ždralovi"})
        assert "zdralovi" in toks
        assert "nogometni" not in toks and "klub" not in toks

    def test_paren_disambiguator_is_not_a_token(self):
        toks = club_tokens({"canonical_name": "NK Mladost (NP)", "city": "Bjelovar"})
        assert toks == {"mladost", "bjelovar"}


class TestZdraloviOwnerScoring:
    """The worked example from the bug report: six clubs, one contact block."""

    @pytest.fixture
    def groups(self):
        return {g.field: g for g in build_groups(ZDRALOVI_COHORT)}

    @pytest.mark.parametrize("field", ["website", "fb_url", "email", "address"])
    def test_zdralovi_owns_every_text_field(self, groups, field):
        verdicts = resolve_group(groups[field])
        assert verdicts[26] == "owner"
        assert all(verdicts[cid] == "orphan" for cid in (224, 416, 804, 853, 888))

    @pytest.mark.parametrize("field", ["phone", "phone_e164"])
    def test_opaque_phone_resolves_via_registry_and_unparen_name(self, groups, field):
        # A phone number contains no place name, so ownership has to be argued
        # from the club's own columns.
        verdicts = resolve_group(groups[field])
        assert verdicts[26] == "owner"
        assert verdicts[888] == "orphan"

    def test_shared_city_token_does_not_outvote_the_specific_one(self, groups):
        # Five clubs match `bjelovar` in the postal address; one matches
        # `zdralovi`. The token claimed by exactly one club must win.
        scores = {m.club["id"]: m.score for m in groups["address"].members}
        assert scores[26] > max(scores[c] for c in (224, 416, 804, 853, 888))

    def test_reasons_are_recorded_for_every_point(self, groups):
        owner = next(m for m in groups["website"].members if m.club["id"] == 26)
        assert "value_token(zdralovi)" in " ".join(owner.reasons)
        assert owner.score == sum(int(r.rsplit("+", 1)[1]) for r in owner.reasons)


class TestAmbiguityIsNotResolved:
    def test_tied_scores_yield_ambiguous_not_a_coin_flip(self):
        # Two clubs, symmetric evidence. Guessing here would delete a real
        # club's only phone number.
        clubs = [
            dict(id=1, slug="a", canonical_name="NK Sloga (A)", city="",
                 phone="+385 91 111 2222", registry_naziv=None),
            dict(id=2, slug="b", canonical_name="NK Sloga (B)", city="",
                 phone="+385 91 111 2222", registry_naziv=None),
        ]
        groups = build_groups(clubs, (FIELDS_BY_NAME["phone"],))
        assert set(resolve_group(groups[0]).values()) == {"ambiguous"}

    def test_no_evidence_at_all_is_ambiguous(self):
        clubs = [
            dict(id=1, slug="a", canonical_name="NK Sloga (A)", city="Zagreb",
                 email="info@example.com"),
            dict(id=2, slug="b", canonical_name="NK Sloga (B)", city="Split",
                 email="info@example.com"),
        ]
        groups = build_groups(clubs, (FIELDS_BY_NAME["email"],))
        assert set(resolve_group(groups[0]).values()) == {"ambiguous"}

    def test_singleton_values_never_form_a_group(self):
        clubs = [
            dict(id=1, slug="a", canonical_name="NK A", city="X", phone="+385911112222"),
            dict(id=2, slug="b", canonical_name="NK B", city="Y", phone="+385913334444"),
        ]
        assert build_groups(clubs, (FIELDS_BY_NAME["phone"],)) == []


class TestGranicarRegistrySignal:
    """Eight clubs share one OIB from a wrong N:1 Registar udruga match. The
    OIB itself is opaque digits, so `registry_naziv` has to carry the verdict —
    and three clubs have unparenthesized names, so that signal cannot."""

    def test_registry_place_names_the_owner(self):
        clubs = [
            dict(id=554, slug="granicar-klakar", canonical_name="NK Graničar Klakar",
                 city="", oib="30169335717", registry_naziv='NOGOMETNI KLUB "GRANIČAR" KLAKAR',
                 semafor_url="https://semafor.hns.family/klubovi/1"),
            dict(id=231, slug="granicar-tucenik", canonical_name="NK Graničar Tučenik",
                 city="", oib="30169335717", registry_naziv='NOGOMETNI KLUB "GRANIČAR" KLAKAR',
                 semafor_url="https://semafor.hns.family/klubovi/2"),
            dict(id=528, slug="granicar-bv", canonical_name="NK Graničar Brodski Varoš",
                 city="", oib="30169335717", registry_naziv='NOGOMETNI KLUB "GRANIČAR" KLAKAR',
                 semafor_url="https://semafor.hns.family/klubovi/3"),
            dict(id=341, slug="granicar-l", canonical_name="NK Graničar (L)",
                 city="", oib="30169335717", registry_naziv='NOGOMETNI KLUB "GRANIČAR" KLAKAR'),
        ]
        groups = build_groups(clubs, (FIELDS_BY_NAME["oib"],))
        verdicts = resolve_group(groups[0])
        assert verdicts[554] == "owner"
        assert verdicts[231] == verdicts[528] == verdicts[341] == "orphan"
