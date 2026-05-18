"""
Scrape president for clubs that have no Registar udruga match.

For each club without a president, try in order:
  1. FB Page About — search the markdown for 'predsjednik' lines
  2. Club website — Firecrawl /v2/scrape with JSON extract
  3. HNS Semafor page — same as above
  4. Firecrawl /v2/search 'NK X predsjednik' → top hit scrape

Fill-if-empty only. Caches Firecrawl responses (the underlying client does
this), so re-runs cost ~0 credits.
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.facebook import canonical_about_url  # noqa: E402
from src.firecrawl import FirecrawlClient  # noqa: E402

DB = ROOT / "data" / "clubs.db"


SCHEMA = {
    "type": "object",
    "properties": {
        "president": {
            "type": "string",
            "description": "Ime i prezime aktualnog predsjednika nogometnog kluba (Croatian: 'predsjednik kluba', 'predsjednik uprave'). Title case. Prazan string ako nije naveden na stranici.",
        },
        "president_role": {"type": "string"},
        "phone": {"type": "string"},
        "email": {"type": "string"},
    },
}
PROMPT = (
    "Iz teksta o ovom hrvatskom nogometnom klubu izvuci ime i prezime "
    "AKTUALNOG predsjednika kluba, njegovu funkciju ako se razlikuje, "
    "telefon i email. Vrati prazan string za polja koja nisu navedena. "
    "Nemoj izmišljati podatke."
)


PRES_LINE = re.compile(
    r"(?:predsjednik(?:\s+kluba|\s+uprave|\s+nogometnog\s+kluba)?)\s*[:\-]?\s*([A-ZČĆĐŠŽ][a-zčćđšž]+(?:[\s\-][A-ZČĆĐŠŽ][a-zčćđšž]+){1,3})",
    re.IGNORECASE,
)


def try_extract(fc: FirecrawlClient, url: str) -> dict[str, Any]:
    try:
        return fc.scrape_json(url, SCHEMA, PROMPT) or {}
    except Exception as e:
        print(f"    scrape err: {e}")
        return {}


def main():
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT id, canonical_name, city, county, fb_url, website, semafor_url "
        "FROM clubs WHERE (president IS NULL OR president='') ORDER BY canonical_name"
    ).fetchall()
    print(f"clubs without president: {len(rows)}")

    fc = FirecrawlClient()
    for i, _ in enumerate(fc.api_keys):
        fc._active_idx = i
        fc._client.headers["Authorization"] = f"Bearer {fc.api_keys[i]}"
        rem = fc.remaining_credits()
        if rem and rem > 100:
            print(f"active key #{i+1}: {rem} credits")
            break
    else:
        raise SystemExit("no key with >100 credits")

    written = 0
    for cid, cname, city, county, fb, web, sem in rows:
        print(f"\n> {cname} ({city or '-'})")
        found = None

        # Try FB about page first
        if fb:
            au = canonical_about_url(fb)
            if au:
                d = try_extract(fc, au)
                if d.get("president"):
                    found = d; print(f"    FB: {d['president']}")
        # Then website
        if not found and web:
            d = try_extract(fc, web)
            if d.get("president"):
                found = d; print(f"    web: {d['president']}")
        # Then semafor page
        if not found and sem:
            d = try_extract(fc, sem)
            if d.get("president"):
                found = d; print(f"    sem: {d['president']}")
        # Last resort: search
        if not found:
            q = f"{cname} predsjednik nogometni klub {city or county or ''}".strip()
            try:
                hits = fc.search(q, limit=3)
                for h in hits[:2]:
                    url = h.get("url")
                    if not url or "facebook.com" in url:
                        continue
                    d = try_extract(fc, url)
                    if d.get("president"):
                        found = d; print(f"    search: {d['president']} ({url})")
                        break
            except Exception as e:
                print(f"    search err: {e}")

        if not found:
            print(f"    (no president found)")
            continue

        sets, vals = ["president=?"], [found["president"]]
        if found.get("president_role"):
            sets.append("president_role=?"); vals.append(found["president_role"])
        if found.get("phone"):
            # only fill phone if currently empty
            cur = conn.execute("SELECT phone FROM clubs WHERE id=?", (cid,)).fetchone()
            if not (cur[0] or "").strip():
                sets.append("phone=?"); vals.append(found["phone"])
        if found.get("email"):
            cur = conn.execute("SELECT email FROM clubs WHERE id=?", (cid,)).fetchone()
            if not (cur[0] or "").strip():
                sets.append("email=?"); vals.append(found["email"])
        sets.append("updated_at=CURRENT_TIMESTAMP")
        sql = f"UPDATE clubs SET {', '.join(sets)} WHERE id=?"
        vals.append(cid)
        conn.execute(sql, vals)
        conn.commit()
        written += 1

    print(f"\nwrote: {written}/{len(rows)} clubs, credits used: {fc.credits_used}")


if __name__ == "__main__":
    main()
