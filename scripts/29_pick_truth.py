"""
Decide whether to keep Nominatim's lat/lng or overwrite it with Google's.

The Nominatim source-of-truth (clubs.lat / clubs.lng) is address-based and
very accurate when the address is clean — but it falls apart when the upstream
address itself is wrong (the Naftaš-via-Velika-Gorica failure) or when the
geocoder picks the wrong place among duplicate toponyms (NK Otok → wrong
Otok). Google's Places API hits an actual POI database, so when its match
name CONTAINS the club's distinctive name token, we trust it.

Decision per club (only fires when both geocoders are present and disagree
by ≥ 500 m):

  1. Compute distinctive tokens of canonical_name (strip prefix + parens +
     stopwords; drop city/county tokens).
  2. Tokenise google_place_name + google_formatted_address.
  3. If any distinctive token is contained in that set AND the Google point is
     in HR AND the Google county (from formatted_address) matches clubs.county,
     overwrite clubs.lat/lng with the Google point. Record the source in
     clubs.geo_source = 'google_places' so we can audit later.
  4. Otherwise keep Nominatim. Record clubs.geo_source = 'nominatim'.

Run with `--dry` to preview without writing.
"""
from __future__ import annotations

import argparse
import math
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.normalize import strip_diacritics  # noqa: E402

DB = ROOT / "data" / "clubs.db"

_PAREN = re.compile(r"\s*\([^)]+\)\s*$")
_QUOTES = re.compile(r"[\"„""'`]")
_PREFIX = re.compile(
    r"^(HNK|GNK|NK|RNK|MNK|HAŠK|HRNK|ŠNK|GŠNK|BŠK|ŠNM|HNŠK)\b",
    re.IGNORECASE,
)
_STOP = {
    "nogometni", "klub", "nogometna", "nogomet", "hrvatski", "gradanski",
    "gradski", "akademski", "radnicki", "omladinski", "sportski",
    "hrvatska", "udruga", "stadion", "stadium", "skola", "athletic",
}

# Reject Google hits that resolved to a foreign country (NK Olimpija Ljubljana).
_NON_HR = (
    "slovenija", "bosna i hercegovina", "srbija", "crna gora", "italija",
    "magyarorszag", "madarska",
)


def tokens(s: str) -> set[str]:
    s = strip_diacritics(s or "").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return {t for t in s.split() if t and t not in _STOP and len(t) >= 3}


def distinctive(canonical: str, city: str | None, county: str | None) -> set[str]:
    n = _QUOTES.sub(" ", canonical or "")
    n = _PAREN.sub("", n).strip()
    n = _PREFIX.sub("", n).strip()
    n = _PREFIX.sub("", n).strip()  # second strip (ŠNM + NK)
    name_t = tokens(n)
    city_t = tokens(city or "")
    cnty_t = tokens((county or "").replace("zupanija", ""))
    distinct = name_t - city_t - cnty_t
    return distinct or name_t  # fall back to all name tokens if city ate it


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 6_371_000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dlat = math.radians(b[0] - a[0])
    dlng = math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def main(dry: bool):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    # Ensure column exists
    cols = {r[1] for r in conn.execute("PRAGMA table_info(clubs)").fetchall()}
    if "geo_source" not in cols:
        conn.execute("ALTER TABLE clubs ADD COLUMN geo_source TEXT")
        conn.commit()

    rows = conn.execute(
        "SELECT id, canonical_name, city, county, lat, lng, lat_google, lng_google, "
        "google_place_name, google_formatted_address, google_match_type "
        "FROM clubs WHERE lat IS NOT NULL AND lat_google IS NOT NULL"
    ).fetchall()
    print(f"paired clubs: {len(rows)}")

    counters = Counter()
    overrides = []
    for r in rows:
        d = haversine_m((r["lat"], r["lng"]), (r["lat_google"], r["lng_google"]))
        if d < 500:
            counters["agree"] += 1
            continue
        # Disagreement: try Google trust rule.
        # Skip if Google resolved to a foreign country (Slovenia, BiH, ...).
        addr_low = strip_diacritics(r["google_formatted_address"] or "").lower()
        if any(c in addr_low for c in _NON_HR):
            counters["foreign_google"] += 1
            continue

        # Skip Google hits that look like a different sport / governing body.
        # Place name must hint football: NK/HNK/GNK prefix, "nogomet*", "FC",
        # "stadion" — otherwise we may grab a sailing club ("Jedriličarski
        # klub Galeb") or a county FA body ("HRVATSKI SOKOL ŽUPANIJE OSIJEK").
        gname_low = strip_diacritics(r["google_place_name"] or "").lower()
        is_football = (
            re.search(r"\b(nk|hnk|gnk|rnk|mnk|znk|snk|šnk|gšnk|hrnk|fc)\b", gname_low)
            or "nogomet" in gname_low
            or "stadion" in gname_low
            or "stadium" in gname_low
        )
        if not is_football:
            counters["nonfootball_google"] += 1
            continue

        distinct = distinctive(r["canonical_name"], r["city"], r["county"])
        g_text = f"{r['google_place_name'] or ''} {r['google_formatted_address'] or ''}"
        g_toks = tokens(g_text)
        hit = bool(distinct & g_toks)
        # Reject generic-name Google hits: canonical with a "(X)" suffix
        # disambiguator means multiple clubs share the bare name. If Google's
        # match name is just "NK Sloboda" (no extra place qualifier) we can
        # not trust the pin — Google returned the most-popular Sloboda, not
        # ours. Require Google to have *more* distinctive tokens than our
        # canonical's bare name.
        has_paren = bool(_PAREN.search(r["canonical_name"] or ""))
        if has_paren:
            canon_core_tokens = tokens(
                _PREFIX.sub("", _PAREN.sub("", r["canonical_name"]).strip())
            )
            g_name_tokens = tokens(
                _PREFIX.sub("", r["google_place_name"] or "").strip()
            )
            extra = g_name_tokens - canon_core_tokens
            if not extra:
                counters["bare_generic_google"] += 1
                continue

        # County guard: most Croatian addresses don't include the county name,
        # only the city and ZIP. So we accept any of:
        #   a) county tokens directly in Google's formatted_address
        #   b) clubs.city overlaps with Google's address
        #   c) a non-city distinctive token from canonical appears in Google's
        #      address (e.g. "Ivanić" from "Naftaš Ivanić" → "Ivanić-Grad")
        county_norm = tokens((r["county"] or "").replace("zupanija", ""))
        city_toks = tokens(r["city"] or "")
        addr_toks = tokens(r["google_formatted_address"] or "")
        county_match = bool(county_norm & g_toks)
        city_match = bool(city_toks & addr_toks)
        name_in_addr = bool((distinct - city_toks - county_norm) & addr_toks)
        county_ok = county_match or city_match or name_in_addr or not county_norm
        if hit and county_ok:
            counters["trust_google"] += 1
            overrides.append({
                "id": r["id"],
                "name": r["canonical_name"],
                "city": r["city"],
                "distance_km": round(d / 1000, 2),
                "google_place": r["google_place_name"] or r["google_formatted_address"],
            })
            if not dry:
                conn.execute(
                    "UPDATE clubs SET lat=?, lng=?, geo_source=?, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (r["lat_google"], r["lng_google"], "google_places", r["id"]),
                )
        else:
            counters["keep_nominatim"] += 1
            if not dry:
                conn.execute(
                    "UPDATE clubs SET geo_source=? WHERE id=? AND geo_source IS NULL",
                    ("nominatim", r["id"]),
                )

    if not dry:
        # Tag agreers as nominatim too (or rather, "both" — they match).
        conn.execute(
            "UPDATE clubs SET geo_source='both' "
            "WHERE lat IS NOT NULL AND lat_google IS NOT NULL "
            "AND geo_source IS NULL"
        )
        conn.commit()

    print(f"\ncounters: {dict(counters)}")
    print(f"\ntop 20 google trust overrides:")
    overrides.sort(key=lambda x: -x["distance_km"])
    for o in overrides[:20]:
        print(f"  {o['distance_km']:6.1f} km  {o['name']:35} | {o['city'] or '-':18} "
              f"-> {o['google_place']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="Preview without writing.")
    main(ap.parse_args().dry)
