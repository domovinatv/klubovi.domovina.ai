"""
Fill president/address/phone/OIB for the 8 top-tier s.d.d. clubs that don't
have an active udruga entry. Source: companywall.hr (deep-linked via Google
site-search through Firecrawl /v2/search).

Idempotent: only writes where the existing column is empty. Records the
companywall URL into clubs.notes for audit.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from firecrawl import FirecrawlClient  # noqa: E402

DB = ROOT / "data" / "clubs.db"

# The 8 s.d.d. clubs whose registry udruga is BRISAN — names + search hints.
CLUBS = [
    ("HNK Hajduk Split", "HNK Hajduk Split s.d.d."),
    ("HNK Rijeka", "HNK Rijeka s.d.d."),
    ("NK Osijek", "NK Osijek s.d.d."),
    ("NK Varaždin", "NK Varaždin s.d.d."),
    ("NK Istra 1961", "NK Istra 1961 s.d.d."),
    ("HNK Vukovar 1991", "HNK Vukovar 1991 s.d.d."),
    ("HNK Cibalia Vinkovci", "HNK Cibalia Vinkovci"),
    ("HNK Gorica", "HNK Gorica s.d.d."),
]

SCHEMA = {
    "type": "object",
    "properties": {
        "director": {
            "type": "string",
            "description": "Ime i prezime predsjednika uprave / direktora trgovačkog društva (Croatian: 'predsjednik uprave', 'član uprave', 'direktor', 'odgovorna osoba'). Title case.",
        },
        "director_role": {
            "type": "string",
            "description": "Funkcija (e.g. 'Predsjednik uprave', 'Direktor', 'Član uprave').",
        },
        "oib": {"type": "string", "description": "11-digit OIB of the company."},
        "address": {
            "type": "string",
            "description": "Full registered address (sjedište) with street, number, postcode and city.",
        },
        "phone": {"type": "string", "description": "Public telephone number, raw formatting OK."},
        "email": {"type": "string", "description": "Public contact email."},
        "founded_year": {
            "type": "integer",
            "description": "Year the company was founded / registered.",
        },
    },
}

PROMPT = (
    "Izvuci podatke o registriranom trgovačkom društvu (s.d.d. / d.o.o.) za "
    "ovaj nogometni klub: ime i prezime predsjednika uprave ili direktora, "
    "njegovu funkciju, OIB, sjedište (puna adresa), telefon, email, godinu "
    "osnivanja. Vrati prazan string za polja koja nisu navedena."
)


def find_url(fc: FirecrawlClient, query: str) -> str | None:
    """Locate the canonical companywall.hr detail URL for a club."""
    full_q = f'site:companywall.hr "{query}"'
    hits = fc.search(full_q, limit=5)
    for h in hits:
        url = h.get("url") or ""
        if re.search(r"companywall\.hr/tvrtka/[^/]+/MM[A-Za-z0-9]+", url):
            return url
    # Fallback: query without site: filter (Firecrawl may use Google natively)
    hits = fc.search(query + " companywall", limit=5)
    for h in hits:
        url = h.get("url") or ""
        if re.search(r"companywall\.hr/tvrtka/[^/]+/MM[A-Za-z0-9]+", url):
            return url
    return None


def main():
    conn = sqlite3.connect(DB)
    fc = FirecrawlClient()
    # Skip exhausted keys up-front so the retry loop in _post doesn't burn its
    # attempt budget on 402s before reaching one with credits.
    for i, _ in enumerate(fc.api_keys):
        fc._active_idx = i
        fc._client.headers["Authorization"] = f"Bearer {fc.api_keys[i]}"
        rem = fc.remaining_credits()
        if rem and rem > 50:
            print(f"active key #{i+1}: {rem} credits")
            break
    else:
        raise SystemExit("no key with >50 credits remaining")
    out = []

    for canonical, search_q in CLUBS:
        row = conn.execute(
            "SELECT id, president, address, phone, oib, founded_year, notes "
            "FROM clubs WHERE canonical_name=?", (canonical,)
        ).fetchone()
        if row is None:
            print(f"  ! {canonical}: NOT IN DB")
            continue
        cid, cur_pres, cur_addr, cur_phone, cur_oib, cur_fy, cur_notes = row

        print(f"  > {canonical} ...", flush=True)
        url = find_url(fc, search_q)
        if not url:
            print(f"    no companywall URL found")
            out.append({"club": canonical, "status": "no_url"})
            continue
        print(f"    {url}")

        try:
            data = fc.scrape_json(url, SCHEMA, PROMPT)
        except Exception as e:
            print(f"    scrape failed: {e}")
            out.append({"club": canonical, "status": "scrape_failed", "url": url})
            continue

        written = {}
        sets, vals = [], []
        if data.get("director") and not (cur_pres or "").strip():
            sets.append("president=?"); vals.append(data["director"]); written["president"] = data["director"]
            if data.get("director_role"):
                sets.append("president_role=?"); vals.append(data["director_role"])
        if data.get("address") and not (cur_addr or "").strip():
            sets.append("address=?"); vals.append(data["address"]); written["address"] = data["address"]
        if data.get("phone") and not (cur_phone or "").strip():
            sets.append("phone=?"); vals.append(data["phone"]); written["phone"] = data["phone"]
        if data.get("oib") and not cur_oib:
            sets.append("oib=?"); vals.append(data["oib"]); written["oib"] = data["oib"]
        if data.get("founded_year") and not cur_fy:
            sets.append("founded_year=?"); vals.append(int(data["founded_year"])); written["founded_year"] = data["founded_year"]
        # Stamp the source URL into registry_url so we can audit
        sets.append("registry_url=?"); vals.append(url)
        sets.append("registry_status=?"); vals.append("SDD_COMPANYWALL")
        sets.append("registry_naziv=?"); vals.append(canonical)
        sets.append("updated_at=CURRENT_TIMESTAMP")
        sql = f"UPDATE clubs SET {', '.join(sets)} WHERE id=?"
        vals.append(cid)
        conn.execute(sql, vals)
        conn.commit()
        out.append({"club": canonical, "status": "ok", "url": url, "written": written, "raw": data})
        print(f"    wrote: {list(written.keys())}")

    print(f"\ncredits used: {fc.credits_used}")
    Path(ROOT / "data" / "raw" / "companywall_sdd.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
