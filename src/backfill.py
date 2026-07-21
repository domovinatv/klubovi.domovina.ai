"""Per-club Firecrawl backfill of contact + meta fields.

Pipeline per club:

  1) firecrawl /v2/search for "<name> <city/county> nogometni klub kontakt"
     -> returns up to N candidate URLs
  2) pick the most-plausible "official" URL via a small heuristic
  3) firecrawl /v2/scrape on that URL with a JSON schema covering our fields
  4) write non-empty fields back to clubs; audit run to backfill_runs

Idempotent thanks to FirecrawlClient response caching.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.collisions import GENERIC_TOKENS, norm_domain
from src.db import connect
from src.firecrawl import FirecrawlClient
from src.hrnogomet import team_county_from_cache
from src.normalize import strip_diacritics
from src.phones import classify as classify_phone, to_e164 as phone_e164

logger = logging.getLogger(__name__)

# Fields we ask Firecrawl to extract — match clubs columns 1:1.
EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "email": {"type": "string", "description": "Primary contact email"},
        "phone": {"type": "string", "description": "Primary contact phone in any format"},
        "address": {"type": "string", "description": "Full postal address of the club"},
        "website": {"type": "string", "description": "Official club website URL"},
        "facebook_url": {"type": "string", "description": "Official Facebook page URL"},
        "instagram_url": {"type": "string", "description": "Official Instagram URL"},
        "twitter_url": {"type": "string", "description": "Official X/Twitter URL"},
        "president_name": {"type": "string", "description": "Current club president full name"},
        "stadium_name": {"type": "string", "description": "Home stadium name"},
        "stadium_capacity": {"type": "integer", "description": "Stadium capacity in seats"},
        "founded_year": {"type": "integer", "description": "Year the club was founded"},
        "city": {"type": "string", "description": "City where the club is based"},
    },
}

EXTRACT_PROMPT = (
    "You are extracting contact and meta information for a Croatian football club. "
    "Return only fields that appear explicitly on the page. Leave fields empty if "
    "not stated. founded_year must be a 4-digit year. URLs must be absolute."
)

# Strip hrnogomet disambiguation suffixes like " (DS)", " (B)", " 1932" — they're
# noise to web search.
_PAREN_RE = re.compile(r"\s*\([A-ZĐŠČŽa-zđšćč0-9]{1,4}\)\s*$")
_PREFIX_RE = re.compile(r"^(HNK|GNK|NK|RNK|MNK|HAŠK|ŠNK|GŠNK)\s+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}")

# County FA / governing-body email patterns — these belong to the FA, not the
# clubs it lists. Reject any email matching these from extraction.
_FA_EMAIL_RE = re.compile(
    r"(?:^|@)(?:nszz|nszns|nszg|nszsd|nsosbz|nsizz|nssmz|nssloga|"
    r"savez|nogometni-savez|hns)\.[a-z]+$|"
    r"^(?:tajnik|info|ured|admin)@(?:nszz|nszns|nssmz|nssloga|hns)",
    re.IGNORECASE,
)

# Domains of top-tier professional clubs — when our club has a paren suffix
# (i.e. it's an amateur namesake), these domains are a false-positive trap.
_PRO_CLUB_DOMAINS = {
    "hajduk.hr", "gnkdinamo.hr", "dinamo.hr", "nkrijeka.hr", "hnk-rijeka.hr",
    "nk-osijek.hr", "nkosijek.hr", "hnk-gorica.hr", "lokomotiva.hr",
    "slaven-belupo.hr", "nk-istra.hr", "nk-istra1961.hr", "varazdin.hr",
    "vukovar1991.hr",
}

# Sites we cannot scrape but whose URL is still worth keeping verbatim.
_SOCIAL_DOMAINS = {"facebook.com", "instagram.com", "twitter.com", "x.com"}

# Empty / placeholder values we should treat as "no data".
def _is_blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and not v.strip():
        return True
    if isinstance(v, int) and v == 0:
        return True
    return False


def search_query(name: str, city: str | None, county: str | None) -> str:
    """Build a single search string with disambiguation noise removed."""
    base = _PAREN_RE.sub("", name).strip()
    loc = city or (county.replace(" županija", "").strip() if county else "")
    bits = [base, loc, "nogometni klub kontakt"]
    return " ".join(b for b in bits if b)


def score_url(url: str, club_name: str) -> int:
    """Rank candidate URLs — bigger = more likely to be the club's home page."""
    url_l = url.lower()
    score = 0
    if url_l.startswith("https://") or url_l.startswith("http://"):
        score += 1
    # Penalize aggregator / wiki / scraping sites — they don't carry contact info.
    if any(d in url_l for d in (
        "wikipedia.org", "transfermarkt", "sofascore", "hrsport.net",
        "sportnet.hr", "index.hr", "24sata", "tportal", "soccerway",
        "fcfutbol", "playmaker", "playmakerstats", "soccerstand",
        # Business registries leak the parent legal entity, not the club.
        "poslovna.hr", "companywall.hr", "sudreg.hr", "fininfo.hr",
        "burzakapital.hr", "boniteti.hr", "fina.hr",
        # County FA / governing-body sites list every club they administer,
        # JSON scrape extracts the FA's own contact for every one of them.
        "nszz.hr", "nszns.hr", "nssmz.hr", "nssloga-cakovec.hr",
        # Pure aggregator sites surfaced by the 2026-05-17 verification audit.
        "hrvatskekarta.com",
        # HNS Semafor profile pages are canonical HNS but they ARE NOT the
        # club's own website — keep the URL elsewhere (clubs.semafor_url)
        # and don't let it through here as a "website".
        "semafor.hns.family",
        # Local-news outlets that occasionally outrank the club itself for
        # search queries about that village's amateur team.
        "dugoselska-kronika.hr", "dugoselski-sport.hr",
        # Municipal-office domains found by 2026-05-17 Run 4 audit
        # (NK Trnski had nova-raca.hr, NK Psunj Sokol had opcokucani...).
        # Any opcina-* / -opcina pattern is the municipality, not the club.
        "opcina-", "-opcina", "opcokucani", "nova-raca",
    )):
        score -= 5
    # Documents (PDF/DOCX) almost always come from FA directories that mix
    # one row per club — LLM extraction frequently grabs the wrong row.
    if url_l.endswith((".pdf", ".docx", ".doc", ".xlsx", ".xls")):
        score -= 8
    # Heavy penalty: pro-club domain when the club is a disambiguated namesake.
    # E.g. "HNK Hajduk (LB)" must never resolve to hajduk.hr.
    if _PAREN_RE.search(club_name):
        if any(dom in url_l for dom in _PRO_CLUB_DOMAINS):
            score -= 20
    if "facebook.com" in url_l:
        # Penalize FB share/dialog links — they're not real profile pages.
        if "/sharer" in url_l or "/dialog" in url_l or "/share" in url_l:
            score -= 10
        else:
            score += 1  # FB pages are useful but lower priority than .hr site
    # Twitter / X share-intent shapes (NOT real profiles): /share, /intent/tweet
    # (already covered by FB block above pattern-wise since "/share" matches),
    # PLUS /home?status= which the Run 4 audit found on ~155 Semafor pages.
    if "twitter.com" in url_l or "x.com" in url_l:
        if "/home?status=" in url_l or "?status=" in url_l or "/intent/tweet" in url_l:
            score -= 10
    if url_l.endswith(".hr") or ".hr/" in url_l:
        score += 3
    # Strong bonus when the URL slug includes parts of the club name.
    name_tokens = {
        t for t in strip_diacritics(_PREFIX_RE.sub("", club_name).lower()).split()
        if len(t) > 2
    }
    if name_tokens and any(t in url_l for t in name_tokens):
        score += 4
    # Prefer pages that look contact-y.
    for kw in ("kontakt", "klub", "contact", "o-klubu", "about"):
        if kw in url_l:
            score += 1
    return score


def pick_url(results: list[dict], club_name: str) -> str | None:
    if not results:
        return None
    scored = sorted(
        ((score_url(r.get("url", ""), club_name), r) for r in results),
        key=lambda x: -x[0],
    )
    top_score, top = scored[0]
    if top_score <= 0:
        return None
    return top.get("url")


# --------------------------------------------------------------------------
# namesake guard
#
# The hrnogomet feed names amateur clubs with a disambiguator but no place —
# `{"id": 1035, "teamName": "NK Mladost (Z)", "countyId": 24}`. Searching that
# name returns every "NK Mladost" in Croatia, and taking the first hit wrote
# NK Mladost Ždralovi's phone, email, website and address onto five other
# clubs. Two independent checks now stand between a search result and a write.
# --------------------------------------------------------------------------

# Ignore digits and very short fragments when comparing place names — "43000"
# and "ul" are not evidence of anything.
_PLACE_TOKEN_RE = re.compile(r"[^a-z]+")
_MIN_PLACE_TOKEN = 4

# Two place tokens count as the same place if they agree on this many leading
# characters: "bjelovar" (address) vs "bjelovarsko" (county adjective).
_PLACE_PREFIX = 6

# Croatian postcodes are five digits whose first two identify the county. This
# is the only county signal that works when the county is not named after its
# capital — "Zabok, 49210" is Krapinsko-zagorska, and no amount of string
# comparison between "zabok" and "krapinsko" would ever discover that.
_POSTCODE_RE = re.compile(r"\b(\d{5})\b")

_POSTCODE_COUNTY = {
    "10": "grad zagreb", "11": "zagrebacka", "20": "dubrovacko-neretvanska",
    "21": "splitsko-dalmatinska", "22": "sibensko-kninska", "23": "zadarska",
    "31": "osjecko-baranjska", "32": "vukovarsko-srijemska",
    "33": "viroviticko-podravska", "34": "pozesko-slavonska",
    "35": "brodsko-posavska", "40": "medimurska", "42": "varazdinska",
    "43": "bjelovarsko-bilogorska", "44": "sisacko-moslavacka",
    "47": "karlovacka", "48": "koprivnicko-krizevacka",
    "49": "krapinsko-zagorska", "51": "primorsko-goranska",
    "52": "istarska", "53": "licko-senjska",
}

# Clubs are routinely filed under either of these two, so a mismatch between
# them is not evidence of a leak.
_ZAGREB_PAIR = {"grad zagreb", "zagrebacka"}


def _norm_county(s: str | None) -> str:
    s = strip_diacritics(str(s or "")).lower()
    s = re.sub(r"\s*zupanija\s*$", "", s).strip()
    return re.sub(r"\s+", " ", s)


def _counties_compatible(a: str, b: str) -> bool:
    a, b = _norm_county(a), _norm_county(b)
    if not a or not b:
        return False
    return a == b or {a, b} <= _ZAGREB_PAIR


def postcode_counties(text: str) -> set[str]:
    """Counties implied by any Croatian postcode appearing in the text."""
    out = set()
    for pc in _POSTCODE_RE.findall(text or ""):
        county = _POSTCODE_COUNTY.get(pc[:2])
        if county:
            out.add(county)
    return out


def _place_tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    toks = {t for t in _PLACE_TOKEN_RE.split(strip_diacritics(str(text)).lower())
            if len(t) >= _MIN_PLACE_TOKEN}
    return toks - GENERIC_TOKENS


def _prefix_match(a: str, b: str) -> bool:
    n = min(len(a), len(b), _PLACE_PREFIX)
    return n >= _PLACE_PREFIX and a[:n] == b[:n]


def resolve_county(conn, club_row: dict) -> str:
    """Club's county, falling back to the hrnogomet `countyId` when the column
    is empty. 31 clubs carry a paren name AND a blank county — exactly the
    rows the old guard skipped outright, so it never fired for them."""
    county = (club_row.get("county") or "").strip()
    if county:
        return county
    row = conn.execute(
        "SELECT alias FROM club_aliases WHERE club_id = ? AND source = 'hrnogomet-id'",
        (club_row["id"],),
    ).fetchone()
    if not row:
        return ""
    try:
        return team_county_from_cache(int(row["alias"])) or ""
    except (TypeError, ValueError):
        return ""


def place_evidence(club_row: dict, county: str, url: str, extracted: dict) -> tuple[bool, str]:
    """Does this source name a place consistent with what we know of the club?

    Signals are tiered by how much they actually pin a location down:

      * `city` and the place part of `registry_naziv` are specific — when we
        have either, the source must corroborate THAT, not merely the county.
      * `county` alone is coarse (Ždralovi and Zabok are both in one county),
        so it is only used when nothing better exists, and it is why the
        ambiguity check below carries the weight for same-county namesakes.
      * no signal at all means we cannot verify, which for a disambiguated
        name is a rejection rather than a free pass.
    """
    blob = " ".join(str(x or "") for x in (
        norm_domain(url) or url,
        extracted.get("address"),
        extracted.get("city"),
        extracted.get("page_title"),
    ))
    found = _place_tokens(blob)
    if not found:
        return False, "source names no place"

    specific = _place_tokens(club_row.get("city"))
    # Registry name = 'NOGOMETNI KLUB "MLADOST" ŽDRALOVI'; drop the club-name
    # tokens so only the place part remains.
    registry = _place_tokens(club_row.get("registry_naziv")) - _place_tokens(
        _PAREN_RE.sub("", club_row.get("canonical_name") or "")
    )
    specific |= registry

    if specific:
        hit = specific & found
        if hit:
            return True, f"specific place match: {','.join(sorted(hit))}"
        return False, (f"expected one of {sorted(specific)}, source names "
                       f"{sorted(found)}")

    if not county:
        return False, "no city, registry or county signal to verify against"

    # A postcode in the address settles the county outright, in both
    # directions: 43000 Ždralovi is Bjelovarsko-bilogorska, 49210 Zabok is
    # Krapinsko-zagorska, and neither town's name resembles its county's.
    pc_counties = postcode_counties(blob)
    if pc_counties:
        if any(_counties_compatible(county, pc) for pc in pc_counties):
            return True, f"postcode county match: {sorted(pc_counties)}"
        return False, (f"postcode implies {sorted(pc_counties)}, club is in "
                       f"{_norm_county(county)}")

    # No postcode. Fall back to the county adjective sharing a stem with a
    # place name, which only fires for counties named after their capital
    # (Bjelovarsko-bilogorska / Bjelovar) but costs nothing when it does not.
    for ct in _place_tokens(county):
        for ft in found:
            if _prefix_match(ct, ft):
                return True, f"county match: {ct}~{ft}"

    return False, (f"no postcode and nothing in {sorted(found)} matches county "
                   f"{_norm_county(county)}")


def namesake_candidates(results: list[dict], club_name: str) -> list[str]:
    """Distinct non-social domains that all look equally like this club.

    For `NK Mladost (Z)` the search returned `mladost-zdralovi.hr` AND
    `nk-mladost-zabok.hr`, both scoring well because both spell "mladost".
    Only one is ours and nothing in the query says which, so the honest answer
    is to write nothing rather than to take whichever sorted first.
    """
    if not _PAREN_RE.search(club_name):
        return []
    scored: dict[str, int] = {}
    for r in results:
        url = r.get("url") or ""
        dom = norm_domain(url)
        if not dom or any(s in dom for s in _SOCIAL_DOMAINS):
            continue
        s = score_url(url, club_name)
        if s > 0:
            scored[dom] = max(scored.get(dom, s), s)
    if len(scored) < 2:
        return []
    top = max(scored.values())
    near = sorted(d for d, s in scored.items() if s >= top - 2)
    return near if len(near) >= 2 else []


def update_club(conn, club_id: int, fields: dict[str, Any]) -> list[str]:
    """Write non-blank, currently-empty fields back to clubs. Returns the set
    we actually wrote (used for the audit trail)."""
    current = dict(conn.execute(
        "SELECT * FROM clubs WHERE id = ?", (club_id,)
    ).fetchone())
    writeable = {
        "email", "phone", "address", "website", "fb_url", "ig_url", "x_url",
        "president", "stadium_name", "stadium_capacity", "founded_year", "city",
    }
    # Translate firecrawl field names to our column names.
    incoming = {
        "email": fields.get("email"),
        "phone": fields.get("phone"),
        "address": fields.get("address"),
        "website": fields.get("website"),
        "fb_url": fields.get("facebook_url"),
        "ig_url": fields.get("instagram_url"),
        "x_url": fields.get("twitter_url"),
        "president": fields.get("president_name"),
        "stadium_name": fields.get("stadium_name"),
        "stadium_capacity": fields.get("stadium_capacity"),
        "founded_year": fields.get("founded_year"),
        "city": fields.get("city"),
    }
    to_write: dict[str, Any] = {}
    for col, val in incoming.items():
        if col not in writeable:
            continue
        if _is_blank(val):
            continue
        # Email sanity: must regex-match AND must not be a county-FA address.
        if col == "email":
            v = str(val).strip()
            if not _EMAIL_RE.fullmatch(v) or _FA_EMAIL_RE.search(v):
                continue
        # Don't overwrite an already-set field — Firecrawl pass is fill-in only.
        if not _is_blank(current.get(col)):
            continue
        to_write[col] = val

    # If phone is being newly set, also populate kind + E.164.
    if "phone" in to_write:
        to_write["phone_kind"] = classify_phone(to_write["phone"])
        to_write["phone_e164"] = phone_e164(to_write["phone"])

    if to_write:
        sets = ", ".join(f"{c} = ?" for c in to_write)
        vals = list(to_write.values()) + [club_id]
        conn.execute(
            f"UPDATE clubs SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            vals,
        )
    # Don't report the derived columns as "filled" — the user-facing fields
    # are just phone + email + ...
    return [k for k in to_write.keys() if k not in ("phone_kind", "phone_e164")]


def backfill_club(
    conn,
    client: FirecrawlClient,
    club_row: dict,
    search_limit: int = 5,
) -> dict[str, Any]:
    name = club_row["canonical_name"]
    # Resolve county up front: it feeds both the search query and the guard,
    # and for 31 paren-named clubs it only exists via the hrnogomet countyId.
    county = resolve_county(conn, club_row)
    query = search_query(name, club_row.get("city"), county)
    logger.info("search: %r", query)

    results = client.search(query, limit=search_limit)
    if not results:
        return {"club_id": club_row["id"], "name": name, "status": "no-results", "fields": []}

    # Guard 1 — two plausible namesakes, no way to choose. Write nothing.
    rivals = namesake_candidates(results, name)
    if rivals:
        logger.warning("ambiguous namesake for %r: %s", name, rivals)
        return {
            "club_id": club_row["id"], "name": name, "status": "ambiguous",
            "candidates": rivals, "fields": [],
        }

    url = pick_url(results, name)
    if not url:
        return {
            "club_id": club_row["id"], "name": name, "status": "no-good-url",
            "candidates": [r.get("url") for r in results[:3]], "fields": [],
        }

    # Social-network URLs can't be scraped (Facebook 403s the firecrawl bot),
    # but the URL itself is still valuable. Record it directly and skip scrape.
    url_l = url.lower()
    if any(dom in url_l for dom in _SOCIAL_DOMAINS):
        social_field = {
            "facebook.com": "facebook_url",
            "instagram.com": "instagram_url",
            "twitter.com": "twitter_url",
            "x.com": "twitter_url",
        }[next(d for d in _SOCIAL_DOMAINS if d in url_l)]
        written = update_club(conn, club_row["id"], {social_field: url})
        conn.execute(
            "INSERT INTO backfill_runs (club_id, fields_filled, source_urls) "
            "VALUES (?, ?, ?)",
            (
                club_row["id"],
                json.dumps(written),
                json.dumps([r.get("url") for r in results[:3]], ensure_ascii=False),
            ),
        )
        return {
            "club_id": club_row["id"], "name": name, "status": "social-only",
            "url": url, "fields": written,
        }

    logger.info("scrape: %s", url)
    try:
        extracted = client.scrape_json(url, EXTRACT_SCHEMA, EXTRACT_PROMPT)
    except RuntimeError as e:
        return {
            "club_id": club_row["id"], "name": name, "status": "scrape-error",
            "url": url, "error": str(e)[:200], "fields": [],
        }

    # Guard 2 — the source must actually name a place we can reconcile with
    # what we already know about this club. Note this runs regardless of
    # whether `county` is populated: the previous version bailed out when
    # county was empty, which is precisely the state of the 31 clubs the
    # namesake leak hit hardest.
    if _PAREN_RE.search(name):
        ok, why = place_evidence(club_row, county, url, extracted)
        if not ok:
            logger.warning("rejecting extraction for %r from %s: %s", name, url, why)
            conn.execute(
                "INSERT INTO backfill_runs (club_id, fields_filled, source_urls) "
                "VALUES (?, ?, ?)",
                (club_row["id"], json.dumps([]),
                 json.dumps([r.get("url") for r in results[:3]], ensure_ascii=False)),
            )
            return {
                "club_id": club_row["id"], "name": name, "status": "place-mismatch",
                "url": url, "reason": why, "fields": [],
            }

    written = update_club(conn, club_row["id"], extracted)
    source_urls = [r.get("url") for r in results[:3]]

    conn.execute(
        "INSERT INTO backfill_runs (club_id, fields_filled, source_urls) VALUES (?, ?, ?)",
        (
            club_row["id"],
            json.dumps(written),
            json.dumps(source_urls, ensure_ascii=False),
        ),
    )
    return {
        "club_id": club_row["id"], "name": name, "status": "ok",
        "url": url, "fields": written, "raw": extracted,
    }
