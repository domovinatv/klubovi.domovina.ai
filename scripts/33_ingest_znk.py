"""Ingest the 20 women's football clubs (ŽNK) discovered by the Semafor BFS
crawl but never added to the catalog.

Background: the 901-club base was built from men's hrnogomet.hr county
leagues; the Semafor crawl (scripts/17c) was used only to *enrich* those 901,
so every club it discovered that wasn't already in the base — including the
whole women's competition — was dropped. This script adds the 20 net-new ŽNK
back in, parsing their already-cached Semafor pages (data/raw/semafor/<id>.html).

Idempotent: skips any club whose slug already exists. Re-runnable.

Run:
    uv run python scripts/33_ingest_znk.py          # dry-run (prints plan)
    uv run python scripts/33_ingest_znk.py --write   # commit inserts
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402
from src.normalize import slugify  # noqa: E402
from src.semafor import parse_club_page, city_from_address, canonical_url  # noqa: E402
from src import phones  # noqa: E402

CACHE = ROOT / "data" / "raw" / "semafor"

# 20 net-new ŽNK Semafor IDs (ŽNK Virovitica already in base, excluded).
ZNK_IDS = [
    107347, 171, 520, 4266, 3440, 108341, 649, 177427, 108137, 119921,
    2603, 107215, 855, 108261, 175029, 175835, 107512, 122895, 179238, 175315,
]

# City → county. Built manually for the 15 distinct cities; reliable and small.
CITY_COUNTY = {
    "Zadar": "Zadarska županija",
    "Osijek": "Osječko-baranjska županija",
    "Višnjevac": "Osječko-baranjska županija",
    "Split": "Splitsko-dalmatinska županija",
    "Rijeka": "Primorsko-goranska županija",
    "Zagreb": "Grad Zagreb",
    "Karlovac": "Karlovačka županija",
    "Đurđevac": "Koprivničko-križevačka županija",
    "Koprivnica": "Koprivničko-križevačka županija",
    "Lepoglava": "Varaždinska županija",
    "Metković": "Dubrovačko-neretvanska županija",
    "Pregrada": "Krapinsko-zagorska županija",
    "Požega": "Požeško-slavonska županija",
    "Čakovec": "Međimurska županija",
    "Stari Mikanovci": "Vukovarsko-srijemska županija",
    "Vinkovci": "Vukovarsko-srijemska županija",
}


def _short(name: str) -> str:
    return name[4:].strip() if name.upper().startswith("ŽNK ") else name


def run(write: bool) -> None:
    conn = connect()
    existing_slugs = {r[0] for r in conn.execute("SELECT slug FROM clubs")}

    planned, skipped = [], []
    for sid in ZNK_IDS:
        html = (CACHE / f"{sid}.html").read_text(errors="ignore")
        d = parse_club_page(html)
        name = (d["short_name"] or "").strip()
        if not name:
            skipped.append((sid, "no name on page"))
            continue
        city = city_from_address(d["address"]) or ""
        county = CITY_COUNTY.get(city, "")
        slug = slugify(name, city or None)
        if slug in existing_slugs:
            skipped.append((sid, f"slug exists: {slug}"))
            continue
        existing_slugs.add(slug)
        phone = d["phone"]
        planned.append({
            "canonical_name": name,
            "slug": slug,
            "short_name": _short(name),
            "city": city or None,
            "county": county or None,
            "founded_year": d["founded_year"],
            "stadium_name": d["stadium_name"],
            "address": d["address"],
            "phone": phone,
            "phone_kind": phones.classify(phone) if phone else None,
            "phone_e164": phones.to_e164(phone) if phone else None,
            "lat": d["lat"],
            "lng": d["lng"],
            "geo_source": "semafor" if (d["lat"] and d["lng"]) else None,
            "semafor_url": canonical_url(sid),
            "notes": "Ženski nogometni klub. Dodano iz HNS Semafor (issue #1).",
        })

    cols = list(planned[0].keys()) if planned else []
    print(f"Plan: {len(planned)} insert, {len(skipped)} skip")
    for p in planned:
        print(f"  + {p['canonical_name']:<26} {p['city'] or '—':<16} "
              f"{p['county'] or '—':<28} osn={p['founded_year'] or '—'} "
              f"koord={'da' if p['lat'] else 'ne'} slug={p['slug']}")
    for sid, why in skipped:
        print(f"  - skip {sid}: {why}")

    if not write:
        print("\n(dry-run — pokreni s --write za upis)")
        return

    placeholders = ",".join(["?"] * len(cols))
    conn.executemany(
        f"INSERT INTO clubs ({','.join(cols)}) VALUES ({placeholders})",
        [tuple(p[c] for c in cols) for p in planned],
    )
    conn.commit()
    print(f"\n✓ Upisano {len(planned)} ŽNK. Ukupno klubova: "
          f"{conn.execute('SELECT count(*) FROM clubs').fetchone()[0]}")


if __name__ == "__main__":
    run(write="--write" in sys.argv)
