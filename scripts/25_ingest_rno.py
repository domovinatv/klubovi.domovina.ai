"""Ingest Registar neprofitnih organizacija (RNO, Ministarstvo financija).

banovac.mfin.hr/rnoprt is a plain ASP.NET Razor app — NO captcha, NO auth,
NO token — unlike the Vaadin Registar udruga SPA. It exposes, keyed by OIB:

  * JSON search   POST /rnoprt/Index?Organizacija.OsobniIdentifikacijskiBrojOrganizacije={OIB}
                  (DataTables server-side; body is a minimal DataTables payload)
                  -> {idOrganizacije, naziv, maticni, adresa, mjesto, aktivan, ...}
  * Stable detail GET  /rnoprt/Details?handler=Details&id={idOrganizacije}
                  -> full HTML with telefon, e-mail, IBAN, kontakt osoba, web,
                     šifra djelatnosti, ovlaštene osobe (richer than Registar udruga)

We store rno_id + rno_url (always refreshed) and fill-if-empty the contact
fields that matter for outreach: phone (+classified), email, website, iban.

Idempotent. Raw responses cached under data/raw/rno/ so re-runs are cheap and
polite. Public data ("podaci su javni"); we still rate-limit modestly.

Usage:
  uv run python scripts/25_ingest_rno.py            # all OIB clubs missing rno_id
  uv run python scripts/25_ingest_rno.py --limit 20 # sanity slice
  uv run python scripts/25_ingest_rno.py --refresh  # re-fetch + re-ingest all
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402
from src.phones import classify, to_e164  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest_rno")

BASE = "https://banovac.mfin.hr/rnoprt/"
CACHE = ROOT / "data" / "raw" / "rno"
# Minimal DataTables server-side payload; the OIB filter travels in the query string.
SEARCH_BODY = (
    '{"draw":1,"start":0,"length":10,'
    '"order":[{"column":0,"dir":"asc"}],"columns":[],'
    '"search":{"value":"","regex":false}}'
)

# Numbered field labels on the Details page -> our key. The page renders each
# datum as "NN. <label> <value>" so we split on the "NN." markers.
FIELD_LABELS = {
    "13": ("adresa", "Adresa sjedišta"),
    "16": ("djelatnost", "Šifra djelatnosti"),
    "17": ("iban", "Račun (IBAN)"),
    "19": ("kontakt", "Osoba za kontakt"),
    "21": ("telefon", "Telefon"),
    "23": ("email", "e-mail"),
    "24": ("web", "Web stranica"),
    "25": ("zastupnik", "Ime i prezime"),
}
# Uppercase section titles that bleed into the last field of a section.
SECTION_CUT = re.compile(r"\s+(PODACI O |OSNOVNI PODACI|IZVJE|POVEZANI|OPCIJE)", re.I)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def session() -> httpx.Client:
    return httpx.Client(
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "klubovi.domovina.ai/1.0 (open catalog; contact stepanic.matija@gmail.com)",
        },
        timeout=30.0,
        follow_redirects=True,
    )


def _get(s: httpx.Client, method: str, url: str, **kw):
    for attempt in range(4):
        try:
            r = s.request(method, url, **kw)
            if r.status_code == 200:
                return r
            log.warning("HTTP %s on %s (try %d)", r.status_code, url, attempt + 1)
        except httpx.HTTPError as e:
            log.warning("req err %s (try %d)", e, attempt + 1)
        time.sleep(0.6 * (attempt + 1))
    return None


def search_oib(s: httpx.Client, oib: str, refresh: bool) -> list[dict]:
    cache = CACHE / f"{oib}.search.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text()).get("data", [])
    r = _get(
        s,
        "POST",
        BASE + "Index",
        params={"Organizacija.OsobniIdentifikacijskiBrojOrganizacije": oib},
        content=SEARCH_BODY,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    if r is None:
        return []
    try:
        j = r.json()
    except ValueError:
        return []
    cache.write_text(json.dumps(j, ensure_ascii=False))
    time.sleep(0.15)
    return j.get("data", [])


def fetch_detail(s: httpx.Client, idorg: int, refresh: bool) -> dict:
    cache = CACHE / f"{idorg}.detail.html"
    if cache.exists() and not refresh:
        text = cache.read_text(encoding="utf-8")
    else:
        r = _get(s, "GET", BASE + "Details", params={"handler": "Details", "id": idorg})
        if r is None:
            return {}
        text = r.text
        cache.write_text(text, encoding="utf-8")
        time.sleep(0.15)
    return parse_detail(text)


def parse_detail(page: str) -> dict:
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", page, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    # Split into numbered fields: [pre, '05', body, '06', body, ...]
    parts = re.split(r"(?<!\d)(\d{2})\.\s", t)
    bodies: dict[str, str] = {}
    for i in range(1, len(parts) - 1, 2):
        bodies[parts[i]] = parts[i + 1].strip()

    out: dict[str, str] = {}
    for num, (key, label) in FIELD_LABELS.items():
        body = bodies.get(num, "")
        if not body:
            continue
        # drop the label prefix
        if body.startswith(label):
            body = body[len(label):].strip()
        # trim trailing section-title bleed
        m = SECTION_CUT.search(body)
        if m:
            body = body[: m.start()].strip()
        if body:
            out[key] = body
    return out


def clean_website(w: str) -> str | None:
    w = w.strip().rstrip("/").strip()
    if not w or "." not in w:
        return None
    if not re.match(r"^https?://", w, re.I):
        w = "https://" + w
    return w


def title_case_name(name: str) -> str:
    return " ".join(w.capitalize() for w in name.split())


def ensure_columns(conn) -> None:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(clubs)").fetchall()}
    for col in ("rno_id", "rno_url", "iban"):
        if col not in cols:
            conn.execute(f"ALTER TABLE clubs ADD COLUMN {col} TEXT")
            log.info("added column %s", col)


def run(limit: int | None, refresh: bool, workers: int) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        ensure_columns(conn)
        q = (
            "SELECT id, canonical_name, oib, phone, email, website, address, "
            "       president, iban, rno_id "
            "FROM clubs WHERE oib IS NOT NULL AND oib != ''"
        )
        rows = [dict(r) for r in conn.execute(q).fetchall()]
        if not refresh:
            rows = [r for r in rows if not r["rno_id"]]
        if limit:
            rows = rows[:limit]
        log.info("clubs to process: %d (refresh=%s)", len(rows), refresh)

        s = session()

        # Phase 1 — fetch (threaded, cached, polite).
        def work(club: dict) -> tuple[dict, dict | None]:
            data = search_oib(s, club["oib"], refresh)
            if len(data) != 1:  # skip 0 (not in RNO) and >1 (ambiguous OIB)
                return club, {"_n": len(data)}
            top = data[0]
            det = fetch_detail(s, top["idOrganizacije"], refresh)
            det["_id"] = top["idOrganizacije"]
            det["_naziv"] = top.get("nazivNeprofitneOrganizacije")
            return club, det

        results: list[tuple[dict, dict | None]] = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(work, c) for c in rows]
            for i, f in enumerate(as_completed(futs), 1):
                results.append(f.result())
                if i % 50 == 0:
                    log.info("fetched %d/%d", i, len(rows))

        # Phase 2 — write (sequential, fill-if-empty).
        stat = {k: 0 for k in ("matched", "no_match", "ambiguous", "phone", "email", "website", "iban", "president")}
        for club, det in results:
            if det is None or det.get("_id") is None:
                if det and det.get("_n", 0) > 1:
                    stat["ambiguous"] += 1
                else:
                    stat["no_match"] += 1
                continue
            stat["matched"] += 1

            sets, vals = [], []
            # always refresh RNO linkage
            rid = str(det["_id"])
            rurl = f"{BASE}Details?handler=Details&id={rid}"
            sets += ["rno_id=?", "rno_url=?"]
            vals += [rid, rurl]

            # fill-if-empty contact fields
            if det.get("telefon") and not (club["phone"] or "").strip():
                # RNO sometimes lists two numbers ("032 … , 098 …"); keep the first
                ph = re.split(r"[,;]", det["telefon"])[0].strip()
                sets += ["phone=?", "phone_kind=?", "phone_e164=?"]
                vals += [ph, classify(ph), to_e164(ph)]
                stat["phone"] += 1
            if det.get("email") and not (club["email"] or "").strip():
                em = det["email"].strip().lower()
                if EMAIL_RE.match(em):
                    sets.append("email=?"); vals.append(em); stat["email"] += 1
            if det.get("web") and not (club["website"] or "").strip():
                w = clean_website(det["web"])
                if w:
                    sets.append("website=?"); vals.append(w); stat["website"] += 1
            if det.get("iban") and not (club["iban"] or "").strip():
                iban = re.sub(r"\s", "", det["iban"])
                if iban.isdigit() and len(iban) >= 15:
                    sets.append("iban=?"); vals.append(iban); stat["iban"] += 1
            if det.get("zastupnik") and not (club["president"] or "").strip():
                pres = title_case_name(det["zastupnik"])
                if 3 <= len(pres) <= 60 and " " in pres:
                    sets += ["president=?", "president_role=?"]
                    vals += [pres, "OSOBA OVLAŠTENA ZA ZASTUPANJE"]
                    stat["president"] += 1

            vals.append(club["id"])
            conn.execute(f"UPDATE clubs SET {', '.join(sets)} WHERE id=?", vals)
        conn.commit()

        log.info(
            "RNO ingest done | matched=%d no_match=%d ambiguous=%d "
            "| filled phone=%d email=%d website=%d iban=%d president=%d",
            stat["matched"], stat["no_match"], stat["ambiguous"],
            stat["phone"], stat["email"], stat["website"], stat["iban"], stat["president"],
        )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    run(a.limit, a.refresh, a.workers)
