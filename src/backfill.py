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

from src.db import connect
from src.firecrawl import FirecrawlClient
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
    r"(?:^|@)(?:nszz|nszns|nszg|nszsd|nsosbz|nsizz|"
    r"savez|nogometni-savez|hns)\.[a-z]+$|"
    r"^(?:tajnik|info|ured)@(?:nszz|nszns|hns)",
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
        "burzakapital.hr", "boniteti.hr",
        # County FA directories list everyone, scrape extracts the FA's own
        # contact for every club it touches.
        "nszz.hr", "nszns.hr",
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
    query = search_query(name, club_row.get("city"), club_row.get("county"))
    logger.info("search: %r", query)

    results = client.search(query, limit=search_limit)
    if not results:
        return {"club_id": club_row["id"], "name": name, "status": "no-results", "fields": []}

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

    # Cross-source validation: if the club is a paren-disambiguated namesake
    # (e.g. "HNK Hajduk (LB)") and the extracted address/city doesn't match
    # the club's county, reject the entire extraction. Big-name lookups
    # commonly leak through aggregator sites that key off the simple name.
    if _PAREN_RE.search(name) and club_row.get("county"):
        county_root = club_row["county"].split()[0].lower()
        addr_blob = " ".join(
            str(extracted.get(k) or "") for k in ("address", "city")
        ).lower()
        if addr_blob and county_root not in addr_blob:
            # Demand the address mention some town that's NOT a known pro-club city.
            for bad in ("split", "zagreb", "rijeka", "osijek", "velika gorica"):
                if bad in addr_blob:
                    logger.warning(
                        "rejecting extraction for %r: address %r doesn't match county %r",
                        name, addr_blob, club_row["county"],
                    )
                    extracted = {}
                    break

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
