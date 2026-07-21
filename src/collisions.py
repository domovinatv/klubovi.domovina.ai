"""Deterministic detection of namesake-leak collisions between clubs.

Background: `src/backfill.py` searched the web by a hrnogomet name carrying a
parenthetical disambiguator but no city (`NK Mladost (Z)`), took the FIRST
search result, and wrote whatever it extracted. When several clubs share a
name, they all inherit ONE club's contact block. The DB ends up with 86 email
groups, 81 phone groups and 73 OIB groups where >=2 clubs share a value that
can only belong to one of them.

This module is the shared, side-effect-free core: value normalization plus a
scoring function that names the most likely OWNER of a shared value. Every
signal is a plain string/set operation over columns already in the DB — there
is no LLM, no network call, and no randomness, so the same DB always yields
the same verdicts.

Owner scoring (points are additive; every awarded point records a reason):

  value_token        the value itself contains a token that is distinctive to
                     exactly one club in the group (`zdralovi` inside
                     `mladost-zdralovi.hr`)                              +5
  value_token_weak   same, but the token is shared by several members and so
                     barely discriminates (`bjelovar` in a postal address) +1
  registry_name      `registry_naziv` from Registar udruga names a place the
                     club's own name/city also names                     +4
  unparen_name       the club is the only one in the group whose canonical
                     name has no `(X)` disambiguator                     +3
  independent_source club is independently attested by Semafor/Sofascore  +2
  cohort_owner       club already won an identically-scoped group, e.g. it
                     owns the website that the phone was scraped from    +3

Verdict per group:
  * exactly one club has the strict top score and that score > 0 -> `owner`,
    everyone else -> `orphan`
  * otherwise every member is `ambiguous` and nothing may be repaired

Ties are deliberately unresolvable. A wrong `owner` verdict deletes a real
club's only contact channel, so the tie-break is "ask a human", not "pick
the lowest id".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from typing import Any, Callable, Iterable

from src.normalize import strip_diacritics
from src.phones import to_e164 as phone_e164

# --------------------------------------------------------------------------
# value normalization
# --------------------------------------------------------------------------

_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_WS_RE = re.compile(r"\s+")

# Club-name prefixes and words that carry no identity. A token from this set
# never discriminates between two clubs, so it must not earn owner points.
GENERIC_TOKENS = {
    "nk", "hnk", "gnk", "rnk", "mnk", "onk", "snk", "znk", "hask", "hrnk",
    "bsk", "snm", "hnsk", "gsnk",
    "nogometni", "nogometna", "nogometno", "nogomet", "klub", "kluba",
    "sportski", "sport", "skolski", "skola", "udruga", "drustvo",
    "hrvatski", "gradanski", "gradski", "omladinski", "opcina", "grad",
}


def _fold(s: str | None) -> str:
    """Lowercase, strip Croatian diacritics, collapse whitespace."""
    if not s:
        return ""
    return _WS_RE.sub(" ", strip_diacritics(str(s)).lower()).strip()


def _alnum(s: str | None) -> str:
    """Fold to a bare [a-z0-9] run — used for substring probes into domains
    and social slugs, where `mladost-zdralovi.hr` must match `zdralovi`."""
    return _NON_ALNUM_RE.sub("", _fold(s))


def norm_phone(v: Any) -> str | None:
    """Croatian phone -> E.164. Reuses src.phones so the DB's own
    `phone_e164` column and this normalization can never disagree."""
    if not v:
        return None
    return phone_e164(str(v))


def norm_email(v: Any) -> str | None:
    if not v:
        return None
    s = _fold(v)
    return s if "@" in s and "." in s.split("@")[-1] else None


def norm_domain(v: Any) -> str | None:
    """URL -> registrable-ish domain: no scheme, no `www.`, no path, no port."""
    if not v:
        return None
    s = _fold(v)
    s = _SCHEME_RE.sub("", s)
    s = s.split("/")[0].split("?")[0].split("#")[0]
    s = s.split("@")[-1]          # strip any user-info prefix
    s = s.split(":")[0]           # strip port
    if s.startswith("www."):
        s = s[4:]
    s = s.strip(".")
    return s or None


def _social_slug(v: Any, host_marker: str) -> str | None:
    """Extract the profile identifier from a Facebook/Instagram URL.

    Share dialogs, `profile.php?id=`, `/people/Name/123` and plain
    `/pageName` all have to collapse to one comparable key, otherwise two
    spellings of the same page look like two different pages.
    """
    if not v:
        return None
    s = _fold(v)
    s = _SCHEME_RE.sub("", s)
    if host_marker not in s:
        return None
    path = s.split(host_marker, 1)[1].lstrip("/")
    if path.startswith("profile.php"):
        m = re.search(r"id=(\d+)", path)
        return f"profile:{m.group(1)}" if m else None
    if path.startswith(("pg/", "pages/", "people/")):
        parts = [p for p in path.split("/") if p]
        path = parts[1] if len(parts) > 1 else ""
    path = path.split("?")[0].split("#")[0].split("/")[0]
    path = path.strip()
    return path or None


def norm_fb(v: Any) -> str | None:
    return _social_slug(v, "facebook.com")


def norm_ig(v: Any) -> str | None:
    return _social_slug(v, "instagram.com")


def norm_oib(v: Any) -> str | None:
    """OIB is exactly 11 digits; anything else is junk we should not group on."""
    if not v:
        return None
    d = "".join(c for c in str(v) if c.isdigit())
    return d if len(d) == 11 else None


def norm_address(v: Any) -> str | None:
    """Fold an address hard enough that `Ul. Kralja Tomislava 5,` and
    `ul kralja tomislava 5` land in the same group."""
    if not v:
        return None
    s = _fold(v)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s or None


def norm_latlng(lat: Any, lng: Any) -> str | None:
    """~1 m precision. Two clubs pinned to the identical coordinate are either
    a shared pitch or a leaked marker — either way worth reporting."""
    if lat is None or lng is None:
        return None
    try:
        return f"{float(lat):.5f},{float(lng):.5f}"
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# field registry
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldSpec:
    """One identity field we group on.

    `token_matchable` says whether the value is text a club name could appear
    inside. Phone numbers and OIBs are opaque digits — ownership of those has
    to be argued from the club's other columns.

    `repair_columns` is what `scripts/61_quarantine_leaks.py` nulls for an
    orphan; nulling `phone` without `phone_e164` would leave the SMS outreach
    filter still pointing at the wrong club.
    """

    name: str
    columns: tuple[str, ...]
    normalizer: Callable[..., str | None]
    token_matchable: bool
    repair_columns: tuple[str, ...]


FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec("phone", ("phone",), norm_phone, False,
              ("phone", "phone_kind", "phone_e164")),
    FieldSpec("phone_e164", ("phone_e164",), norm_phone, False,
              ("phone", "phone_kind", "phone_e164")),
    FieldSpec("email", ("email",), norm_email, True, ("email",)),
    FieldSpec("website", ("website",), norm_domain, True, ("website",)),
    FieldSpec("fb_url", ("fb_url",), norm_fb, True, ("fb_url",)),
    FieldSpec("ig_url", ("ig_url",), norm_ig, True, ("ig_url",)),
    FieldSpec("oib", ("oib",), norm_oib, False, ("oib",)),
    FieldSpec("address", ("address",), norm_address, True, ("address",)),
    FieldSpec("latlng", ("lat", "lng"), norm_latlng, False, ("lat", "lng")),
)

# Registry identity travels as a bundle: an OIB copied from a namesake also
# dragged that namesake's president and registry links along. Nulling only
# `oib` would leave the visible-but-wrong president in place.
REGISTRY_BUNDLE = (
    "oib", "udruga_id", "president", "president_role",
    "registry_status", "registry_naziv", "registry_url",
)

# Likewise a leaked coordinate poisoned the verification columns that were
# derived from it.
GEO_BUNDLE = ("lat", "lng", "geo_source", "geo_truth_source")

FIELDS_BY_NAME = {spec.name: spec for spec in FIELD_SPECS}

# `NK Mladost (Z)` — the hrnogomet disambiguator that started all of this.
PAREN_RE = re.compile(r"\(\s*[^)]{1,12}\s*\)")


# --------------------------------------------------------------------------
# tokens
# --------------------------------------------------------------------------


def club_tokens(club: dict) -> set[str]:
    """Identity tokens for a club: name words plus city words, minus the
    generic football vocabulary that every club shares."""
    blob = f"{club.get('canonical_name') or ''} {club.get('city') or ''}"
    blob = PAREN_RE.sub(" ", blob)
    toks = {t for t in re.split(r"[^a-z0-9]+", _fold(blob)) if len(t) >= 4}
    return toks - GENERIC_TOKENS


def registry_tokens(club: dict) -> set[str]:
    """Same treatment for the Registar udruga name, so `NOGOMETNI KLUB
    "GRANIČAR" KLAKAR` reduces to `{granicar, klakar}`."""
    toks = {
        t for t in re.split(r"[^a-z0-9]+", _fold(club.get("registry_naziv")))
        if len(t) >= 4
    }
    return toks - GENERIC_TOKENS


def has_paren(club: dict) -> bool:
    return bool(PAREN_RE.search(club.get("canonical_name") or ""))


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------


@dataclass
class Scored:
    club: dict
    score: int = 0
    reasons: list[str] = dc_field(default_factory=list)

    def add(self, points: int, reason: str) -> None:
        if points:
            self.score += points
            self.reasons.append(f"{reason}+{points}")


@dataclass
class Group:
    field: str
    key: str            # normalized shared value
    members: list[Scored]

    @property
    def club_ids(self) -> frozenset[int]:
        return frozenset(m.club["id"] for m in self.members)


def score_group(spec: FieldSpec, key: str, clubs: list[dict]) -> Group:
    """Score every club in one collision group. Pure — no DB, no I/O."""
    members = [Scored(club=c) for c in clubs]

    # A token every member carries (all six clubs are "Mladost") proves
    # nothing. Distinctive tokens are what a club does NOT share with the
    # whole group.
    token_sets = {m.club["id"]: club_tokens(m.club) for m in members}
    common = set.intersection(*token_sets.values()) if token_sets else set()
    distinctive = {cid: toks - common for cid, toks in token_sets.items()}

    if spec.token_matchable:
        probe = _alnum(key)
        # How many members can claim each token? A token matched by five of
        # six members (a shared postal city) is near-worthless evidence; a
        # token matched by exactly one is decisive.
        claimants: dict[str, int] = {}
        for m in members:
            for tok in distinctive[m.club["id"]]:
                if tok in probe:
                    claimants[tok] = claimants.get(tok, 0) + 1
        for m in members:
            hits = [t for t in distinctive[m.club["id"]] if t in probe]
            if not hits:
                continue
            unique = [t for t in hits if claimants[t] == 1]
            if unique:
                m.add(5, f"value_token({','.join(sorted(unique))})")
            else:
                m.add(1, f"value_token_weak({','.join(sorted(hits))})")

    # Registar udruga corroboration: the registry name points at the same
    # place the club's own name/city points at.
    for m in members:
        reg = registry_tokens(m.club) - common
        if reg and (reg & distinctive[m.club["id"]]):
            m.add(4, f"registry_name({','.join(sorted(reg & distinctive[m.club['id']]))})")

    # Sole club without a `(X)` disambiguator — the feed itself treated it as
    # the unqualified holder of the name.
    unparen = [m for m in members if not has_paren(m.club)]
    if len(unparen) == 1 and len(members) > 1:
        unparen[0].add(3, "unparen_name")

    # Independent attestation that this club exists as a distinct entity.
    for m in members:
        if m.club.get("semafor_url") or m.club.get("sofascore_url"):
            m.add(2, "independent_source")

    return Group(field=spec.name, key=key, members=members)


def apply_cohort_bonus(groups: list[Group]) -> None:
    """Second pass: propagate a settled owner across identically-scoped groups.

    The Ždralovi cohort shares website, phone, email AND address — the exact
    same six clubs each time. The website group resolves cleanly because the
    domain spells out `zdralovi`; the phone group has no text to reason about.
    Since both groups have the identical member set, the club that provably
    owns the domain also owns the number that was scraped from it.

    Only groups with an identical club-id set count. A merely overlapping
    group is not evidence — that is how one bad verdict would cascade.
    """
    owners_by_cohort: dict[frozenset[int], set[int]] = {}
    for g in groups:
        verdicts = resolve_group(g)
        for cid, verdict in verdicts.items():
            if verdict == "owner":
                owners_by_cohort.setdefault(g.club_ids, set()).add(cid)

    for g in groups:
        owners = owners_by_cohort.get(g.club_ids)
        if not owners:
            continue
        for m in g.members:
            if m.club["id"] in owners and "cohort_owner" not in " ".join(m.reasons):
                # Skip groups this club already won outright — the bonus is
                # for the groups it could not win on its own evidence.
                if resolve_group(g).get(m.club["id"]) != "owner":
                    m.add(3, "cohort_owner")


def resolve_group(group: Group) -> dict[int, str]:
    """Map club_id -> 'owner' | 'orphan' | 'ambiguous' for one group."""
    if len(group.members) < 2:
        return {m.club["id"]: "ambiguous" for m in group.members}
    ranked = sorted(group.members, key=lambda m: -m.score)
    top = ranked[0]
    runner_up = ranked[1]
    if top.score <= 0 or top.score == runner_up.score:
        return {m.club["id"]: "ambiguous" for m in group.members}
    return {
        m.club["id"]: ("owner" if m.club["id"] == top.club["id"] else "orphan")
        for m in group.members
    }


def build_groups(clubs: Iterable[dict], specs: Iterable[FieldSpec] = FIELD_SPECS) -> list[Group]:
    """Full detection pass: group by every identity field, score, then apply
    the cohort bonus. Returns groups with >=2 members only."""
    clubs = list(clubs)
    groups: list[Group] = []
    for spec in specs:
        buckets: dict[str, list[dict]] = {}
        for club in clubs:
            args = [club.get(col) for col in spec.columns]
            key = spec.normalizer(*args)
            if key:
                buckets.setdefault(key, []).append(club)
        for key, members in sorted(buckets.items()):
            if len(members) >= 2:
                groups.append(score_group(spec, key, members))
    apply_cohort_bonus(groups)
    return groups
