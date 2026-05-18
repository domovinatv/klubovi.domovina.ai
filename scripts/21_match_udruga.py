"""
Match 901 clubs to Registar udruga (data.gov.hr CTS).

Strategy:
- Pre-filter CTS to football-only AKTIVAN udruge.
- Score each club against CTS rows with rapidfuzz on:
    name_score   = WRatio(canonical_norm, naziv_norm)
    city_score   = whether club city is contained in CTS sjediste (or vice-versa)
    status_score = AKTIVAN > rest
- Accept if name_score >= 88 OR (>= 75 AND city_match).
- Resolve ties by status, then by city_match, then by name_score.
- Persist matches + ambiguous + unmatched to data/raw/udruge/match_report.json.
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from rapidfuzz import fuzz, process

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from normalize import strip_diacritics  # noqa: E402

csv.field_size_limit(sys.maxsize)

CTS_PATH = ROOT / "data" / "raw" / "udruge" / "cts.csv"
DB_PATH = ROOT / "data" / "clubs.db"
OUT_PATH = ROOT / "data" / "raw" / "udruge" / "match_report.json"

# Drop CTS rows that are obviously non-football despite containing "nogomet" in
# their name (school clubs, women's, futsal, table-football, fan clubs, ...).
EXCLUDE_RE = re.compile(
    r"\b("
    r"malonogometni|mala nogometna|mini ?nogometni|stolnonogometni|"
    r"zenski nogometni|veteranski nogometni|veterani|"
    r"skola nogometa|nogometna omladinska skola|skolski sport(ski)?|"
    r"udruga prijatelja|drustvo prijatelja|udruga navijaca|klub navijaca|"
    r"americkog nogometa|klub americkog nogometa|teqball|futsal|"
    r"nogometni delegati|zbor nogometnih|nogometno srediste|"
    r"savez nogometnih|nogometn[aei] (sluzbenici|treneri|suci|delegati)"
    r")\b"
)

# After stripping these, what's left is the distinctive club identity.
# Keep distinctive brand-letters (HAŠK, HRNK, GSNK) as tokens — they are part
# of the club identity, not a generic prefix.
PREFIX_RE = re.compile(
    r"^\s*("
    r"gradanski nogometni klub|gradski nogometni klub|hrvatski nogometni klub|"
    r"hrvatski radnicki nogometni klub|hrvatski akademski nogometni klub|"
    r"omladinski nogometni klub|skolski nogometni klub|sportski nogometni klub|"
    r"nogometni klub|nogometna udruga|nogometni|nogomet|"
    r"hnk|gnk|nk|rnk|mnk|onk|snk|znk"
    r")\b\s*"
)


def norm(s: str | None) -> str:
    s = strip_diacritics(s or "").lower()
    s = re.sub(r"[„""«»`'\"]+", " ", s)
    # "N.K." and similar acronyms: collapse before stripping punctuation so
    # the abbreviation survives as a single token (otherwise we end up with
    # stray "n" / "k" tokens that pollute the comparison).
    s = re.sub(r"\b([a-z])\.([a-z])\.", r"\1\2", s)
    s = re.sub(r"\b([a-z])\.([a-z])\.([a-z])\.", r"\1\2\3", s)
    # Drop remaining punctuation (commas, dashes, brackets, etc.).
    s = re.sub(r"[.,;:!?/\\()\[\]{}]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def strip_prefix(s: str) -> str:
    s = norm(s)
    # strip up to 2 prefix tokens (e.g., "nogometni klub hrvatski ..." rare)
    for _ in range(2):
        new = PREFIX_RE.sub("", s)
        if new == s:
            break
        s = new
    return s.strip()


def city_from_sjediste(s: str | None) -> str:
    s = norm(s)
    s = re.sub(r"[^a-z0-9, ]+", " ", s)
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if not parts:
        return ""
    last = parts[-1]
    last = re.sub(r"\b\d{4,5}\b", "", last).strip()
    return " ".join(last.split())


def city_match(club_city: str, cts_sjediste: str) -> bool:
    a = norm(club_city)
    b = city_from_sjediste(cts_sjediste)
    if not a or not b:
        return False
    return a in b or b in a


def normalize_county(s: str | None) -> str:
    """Normalise county strings so DB ('X županija', 'Grad Zagreb') and CTS
    ('X', 'Grad Zagreb') can be compared."""
    if not s:
        return ""
    s = strip_diacritics(s).lower().strip()
    s = re.sub(r"\s+zupanija\s*$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load_cts() -> list[dict]:
    rows: list[dict] = []
    with CTS_PATH.open(encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            naziv_n = norm(row["NAZIV"])
            if EXCLUDE_RE.search(naziv_n):
                continue
            # Require "nogomet" in the full NAZIV — using SKRACENI as a
            # fallback admits collisions like "HASK" (skating club). Genuine
            # football clubs always have "Nogometni" / "Nogomet-" somewhere.
            if "nogomet" not in naziv_n:
                continue
            row["_naziv_norm"] = naziv_n
            row["_short_norm"] = strip_prefix(row["NAZIV"])
            row["_short_norm_sk"] = strip_prefix(row.get("SKRACENI_NAZIV") or "")
            row["_city"] = city_from_sjediste(row["SJEDISTE"])
            row["_county"] = normalize_county(row.get("ZUPANIJA"))
            rows.append(row)
    return rows


STATUS_RANK = {"AKTIVAN": 3, "PRESTANAK DJELOVANJA": 2, "BRISAN": 1}


_GENERIC = {"klub", "nogometni", "nogometna", "nogomet", "sportski", "sport",
            "skola", "udruga", "hrvatski", "gradanski", "gradski"}


def best_match(cname: str, ccity: str, cts: list[dict], ccounty: str = ""):
    ccnty = normalize_county(ccounty)
    cn_full = norm(cname)
    cn_short = strip_prefix(cname)
    cc_norm = norm(ccity)
    cc_tokens = set(cc_norm.split())
    cn_short_tokens = set(cn_short.split()) - _GENERIC
    # If explicit city is missing, infer it as the trailing token(s) of the
    # canonical short name when there's more than one token left.
    if not cc_tokens:
        cn_parts = cn_short.split()
        if len(cn_parts) >= 2:
            cc_tokens = {cn_parts[-1]}
    # Distinctive tokens = anything in the canonical short name beyond the city
    distinctive = cn_short_tokens - cc_tokens
    city_only = len(distinctive) == 0  # team name is just the city (e.g. NK Osijek)

    # Pre-narrow: rows whose name shares any short-form token (we still need
    # candidates to score even when distinctive is empty).
    probe = cn_short_tokens if not city_only else cc_tokens
    candidates = []
    for row in cts:
        rt = set(row["_short_norm"].split()) | set(row["_short_norm_sk"].split())
        if probe & rt or fuzz.partial_ratio(cn_short, row["_short_norm"]) >= 80:
            candidates.append(row)
    # Hard county gate: if we know the club's county, drop CTS rows from a
    # different county. This kills the "Hajduk Tovarnik wins for Hajduk Bjelovar"
    # failure mode. Grad Zagreb and Zagrebačka are treated as compatible (clubs
    # often misfiled between them).
    if ccnty:
        zagreb_pair = {"grad zagreb", "zagrebacka"}
        kept = []
        for row in candidates:
            rc = row["_county"]
            if not rc:
                kept.append(row); continue
            if rc == ccnty:
                kept.append(row); continue
            if {rc, ccnty} <= zagreb_pair:
                kept.append(row); continue
        candidates = kept
    if not candidates:
        return None, []

    scored = []
    for row in candidates:
        rt = set(row["_short_norm"].split()) | set(row["_short_norm_sk"].split())
        rt_clean = rt - _GENERIC
        # Hard requirement: at least one distinctive club token must appear
        # in the CTS short name. Skip candidates that fail this — protects
        # against "NK Osijek -> Olimpija Osijek" style false positives.
        if not city_only:
            if not (distinctive & rt_clean):
                continue
        else:
            # For city-only canonical names (NK Osijek, HNK Rijeka), require
            # that the CTS short name is *also* essentially just the city.
            # Extra non-city tokens in the registry name mean a different club.
            extras = rt_clean - cc_tokens
            if extras:
                continue
        # WRatio over full + short forms
        a = fuzz.WRatio(cn_full, row["_naziv_norm"])
        b = fuzz.WRatio(cn_short, row["_short_norm"]) if row["_short_norm"] else 0
        c = fuzz.WRatio(cn_short, row["_short_norm_sk"]) if row["_short_norm_sk"] else 0
        d = fuzz.token_set_ratio(cn_short, row["_short_norm"]) if row["_short_norm"] else 0
        e = fuzz.token_set_ratio(cn_short, row["_short_norm_sk"]) if row["_short_norm_sk"] else 0
        name_score = max(a, b, c, d, e)
        # Overlap is the count of distinctive club tokens present in CTS short.
        # (City tokens don't earn points — they're disambiguated via SJEDISTE.)
        overlap = len((distinctive or cn_short_tokens) & rt_clean)
        cm = city_match(ccity, row["SJEDISTE"])
        srank = STATUS_RANK.get(row["STATUS"], 0)
        scored.append((name_score, int(cm), srank, overlap, row))

    if not scored:
        return None, []
    # Rank: city-match, then token overlap (more shared distinctive tokens
    # beats AKTIVAN-only — protects against "NK Istra 1961 -> Istra Cement"),
    # then status, then name score.
    scored.sort(reverse=True, key=lambda x: (x[1], x[3], x[2], x[0]))
    flat = [(s[0], s[1], s[2], s[4]) for s in scored]
    return flat[0], flat[:5]


def main():
    cts = load_cts()
    print(f"CTS football-only rows: {len(cts)}", file=sys.stderr)

    conn = sqlite3.connect(DB_PATH)
    clubs = conn.execute(
        "SELECT id, canonical_name, city, county, president FROM clubs ORDER BY id"
    ).fetchall()

    matched = {}
    ambig = []
    nomatch = []
    low_conf = []

    for cid, cname, ccity, ccounty, pres in clubs:
        best, top5 = best_match(cname, ccity or "", cts, ccounty or "")
        if best is None:
            nomatch.append({"id": cid, "name": cname, "city": ccity})
            continue
        name_score, cm, srank, row = best
        # Acceptance rules — top-ranked candidate wins if it crosses a
        # confidence threshold. We do NOT re-flag ties: the ranking already
        # prefers city-match + AKTIVAN + token overlap.
        accept = False
        confidence = "low"
        if cm and name_score >= 80:
            accept = True; confidence = "high" if name_score >= 90 else "med"
        elif name_score >= 88:
            accept = True; confidence = "med"
        elif cm and name_score >= 70 and srank == 3:
            accept = True; confidence = "low"
        if accept:
            matched[cid] = {
                "udr_id": row["UDR_ID"],
                "oib": row["OIB"],
                "naziv": row["NAZIV"],
                "sjediste": row["SJEDISTE"],
                "status": row["STATUS"],
                "mail": row.get("MAIL") or None,
                "web": row.get("WEB_STRANICA") or None,
                "datum_upisa": row.get("DATUM_UPISA") or None,
                "datum_osn": row.get("DATUM_OSNIVACKE_SKUPSTINE") or None,
                "name_score": name_score,
                "city_match": bool(cm),
                "confidence": confidence,
            }
        else:
            low_conf.append({
                "id": cid, "name": cname, "city": ccity,
                "candidates": [
                    {"score": s, "city_match": bool(c), "status": r["STATUS"],
                     "udr_id": r["UDR_ID"], "naziv": r["NAZIV"], "sjediste": r["SJEDISTE"], "oib": r["OIB"]}
                    for s, c, _, r in top5
                ],
            })

    report = {
        "summary": {
            "total_clubs": len(clubs),
            "matched": len(matched),
            "ambig": len(ambig),
            "low_conf": len(low_conf),
            "nomatch": len(nomatch),
        },
        "matched": matched,
        "ambig": ambig[:30],
        "low_conf": low_conf[:50],
        "nomatch": nomatch,
    }
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
