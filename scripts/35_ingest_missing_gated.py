"""Gated ingest of the remaining non-ŽNK clubs discovered by the Semafor crawl
but never added (see MISSING_CLUBS.md / issue #1).

Quality gate (STRICT, user-chosen): a candidate is kept ONLY if, after the full
geo pipeline runs, it reaches geo_source='both' (Nominatim address geocode AND
Google Places agree) and sits inside the HR bounding box. Everything else is
removed from the DB and written to a review CSV — we do not pollute the catalog
with unverifiable locations.

Controlled / reversible: every inserted row is tagged in `notes` with a batch
marker so the gate phase deletes EXACTLY this batch and nothing else. Re-runnable
from the local Semafor cache at any time.

Workflow (run phases in order):
    uv run python scripts/35_ingest_missing_gated.py --insert     # stage candidates
    uv run python scripts/10_geocode_nominatim.py                  # fills lat (lat IS NULL)
    uv run python scripts/27_google_geocode.py --only-missing      # parallel Google
    uv run python scripts/29_pick_truth.py                         # sets geo_source
    uv run python scripts/35_ingest_missing_gated.py --gate        # keep 'both', drop rest
"""
from __future__ import annotations

import csv
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402
from src.normalize import slugify  # noqa: E402
from src.semafor import parse_club_page, city_from_address, canonical_url, extract_club_id  # noqa: E402
from src import phones  # noqa: E402

CACHE = ROOT / "data" / "raw" / "semafor"
UNLINKED = Path("/tmp/unlinked.txt")
REVIEW_CSV = ROOT / "data" / "exports" / "missing_clubs_gate_rejects.csv"
BATCH_TAG = "ingest-batch:35-missing-gated"

# HR bounding box (same as scripts/26_verify_geo.py)
LAT_MIN, LAT_MAX = 42.30, 46.60
LNG_MIN, LNG_MAX = 13.40, 19.50

# City→county; extends the ŽNK map. Falls back to a DB lookup by city.
CITY_COUNTY_SEED = {
    "Zagreb": "Grad Zagreb",
}


def _strip(s: str) -> str:
    s = (s or "").lower()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _klass(name: str) -> str:
    u = _strip(name)
    if u.startswith("znk") or "zenski" in u:
        return "Z"
    if u.startswith("mnk") or "futsal" in u or "malonog" in u:
        return "F"
    return "M"


def _core(name: str) -> str:
    s = re.sub(r"\b(znk|nk|hnk|snk|nsk|gnk|rnk|onk|hrnk|hnsk|snm|sn|ofk|mnk|nso|ns)\b", "", _strip(name))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _is_reserve(name: str) -> bool:
    return bool(re.search(r"\bii\b|\(b\)|\b2\b|\bi\b$", _strip(name)))


def _candidates(conn):
    base_keys = {(_klass(n), _core(n)) for (n,) in conn.execute("SELECT canonical_name FROM clubs")}
    city_county = dict(CITY_COUNTY_SEED)
    for city, county in conn.execute(
        "SELECT city, county FROM clubs WHERE city IS NOT NULL AND county IS NOT NULL"
    ):
        city_county.setdefault(city, county)

    out = []
    for line in UNLINKED.read_text().splitlines():
        sid = line.strip()
        if not sid:
            continue
        page = CACHE / f"{sid}.html"
        if not page.exists():
            continue
        d = parse_club_page(page.read_text(errors="ignore"))
        name = (d["short_name"] or "").strip()
        if not name or _klass(name) == "Z":          # ŽNK already ingested
            continue
        if (_klass(name), _core(name)) in base_keys:  # class-aware dedup
            continue
        if _is_reserve(name):                          # skip II/B/I reserve teams
            continue
        if not d["address"]:                           # gate precondition: must be geocodable
            continue
        city = city_from_address(d["address"]) or ""
        out.append((sid, name, d, city, city_county.get(city)))
    return out


def insert(conn) -> None:
    cands = _candidates(conn)
    existing = {s for (s,) in conn.execute("SELECT slug FROM clubs")}
    rows = []
    for sid, name, d, city, county in cands:
        slug = slugify(name, city or None)
        if slug in existing:
            continue
        existing.add(slug)
        phone = d["phone"]
        rows.append({
            "canonical_name": name, "slug": slug,
            "short_name": re.sub(r"^(NK|HNK|GNK|RNK|ŠNK|NŠK|MNK)\s+", "", name).split()[0] if name else name,
            "city": city or None, "county": county,
            "founded_year": d["founded_year"], "stadium_name": d["stadium_name"],
            "address": d["address"], "phone": phone,
            "phone_kind": phones.classify(phone) if phone else None,
            "phone_e164": phones.to_e164(phone) if phone else None,
            "lat": d["lat"], "lng": d["lng"],
            "geo_source": "semafor" if (d["lat"] and d["lng"]) else None,
            "semafor_url": canonical_url(int(sid)),
            "notes": f"Dodano iz HNS Semafor (issue #1). {BATCH_TAG}",
        })
    cols = list(rows[0].keys())
    conn.executemany(
        f"INSERT INTO clubs ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})",
        [tuple(r[c] for c in cols) for r in rows],
    )
    conn.commit()
    print(f"✓ Staged {len(rows)} candidates (tag: {BATCH_TAG})")
    print(f"  total clubs now: {conn.execute('SELECT count(*) FROM clubs').fetchone()[0]}")
    print("  next: run 10_geocode_nominatim → 27_google_geocode --only-missing → 29_pick_truth → --gate")


def gate(conn) -> None:
    batch = conn.execute(
        "SELECT id, canonical_name, city, lat, lng, geo_source, "
        "google_place_name, google_formatted_address "
        "FROM clubs WHERE notes LIKE ?", (f"%{BATCH_TAG}%",),
    ).fetchall()

    keep, reject = [], []
    for r in batch:
        cid, name, city, lat, lng, gsrc, gplace, gaddr = r
        in_bbox = lat is not None and LAT_MIN <= lat <= LAT_MAX and LNG_MIN <= lng <= LNG_MAX
        if gsrc == "both" and in_bbox:
            keep.append(r)
        else:
            why = []
            if gsrc != "both":
                why.append(f"geo_source={gsrc or 'none'} (not 'both')")
            if not in_bbox:
                why.append("outside HR bbox")
            reject.append((r, "; ".join(why)))

    # write review CSV for the rejects, then remove them from the catalog
    REVIEW_CSV.parent.mkdir(parents=True, exist_ok=True)
    with REVIEW_CSV.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "naziv", "grad", "lat", "lng", "geo_source",
                    "google_place", "google_address", "razlog_odbijanja"])
        for (cid, name, city, lat, lng, gsrc, gplace, gaddr), why in reject:
            w.writerow([cid, name, city, lat, lng, gsrc, gplace, gaddr, why])

    reject_ids = [r[0][0] for r in reject]
    if reject_ids:
        conn.executemany("DELETE FROM clubs WHERE id=?", [(i,) for i in reject_ids])
        conn.commit()

    print(f"GATE (strict 'both' + HR bbox):")
    print(f"  KEEP:   {len(keep)} clubs imported & geo-verified")
    print(f"  REJECT: {len(reject)} removed → review at {REVIEW_CSV}")
    print(f"  total clubs now: {conn.execute('SELECT count(*) FROM clubs').fetchone()[0]}")


if __name__ == "__main__":
    conn = connect()
    if "--insert" in sys.argv:
        insert(conn)
    elif "--gate" in sys.argv:
        gate(conn)
    else:
        print("usage: --insert  (stage candidates)  |  --gate  (keep 'both', drop rest)")
