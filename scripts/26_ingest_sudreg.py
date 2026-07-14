"""Classify clubs against the Sudski registar (court register) open-data API.

sudreg-data.gov.hr — OAuth2 client_credentials (creds in .env:
SUDREG_CLIENT_ID / SUDREG_CLIENT_SECRET). The `detalji_subjekta` endpoint,
queried by OIB, returns a company's legal form, share capital, seat, email,
court, etc. Non-companies (udruge) 404 — so a 200 here means the club's stored
OIB belongs to a trgovačko društvo, and if the name says "sportsko dioničko
društvo" it is an s.d.d.

We store sudreg_mbs, pravni_oblik, is_sdd, temeljni_kapital(+valuta) and
fill-if-empty email. This gives a definitive answer to "which clubs are s.d.d."
that our earlier manual CompanyWall pass could only approximate.

Shareholder/management persons are NOT in the public tier (dionice sit at SKDD,
knjiga dionica is not open) — so no cap-table here, by design.

Idempotent; raw JSON cached under data/raw/sudreg/. Token valid 6h.

Usage:
  uv run python scripts/26_ingest_sudreg.py            # all OIB clubs
  uv run python scripts/26_ingest_sudreg.py --limit 15
  uv run python scripts/26_ingest_sudreg.py --refresh
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest_sudreg")

API = "https://sudreg-data.gov.hr/api"
CACHE = ROOT / "data" / "raw" / "sudreg"
EMAIL_RE = __import__("re").compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def get_token() -> str:
    load_dotenv(ROOT / ".env")
    cid, secret = os.environ.get("SUDREG_CLIENT_ID"), os.environ.get("SUDREG_CLIENT_SECRET")
    if not cid or not secret:
        sys.exit("Missing SUDREG_CLIENT_ID / SUDREG_CLIENT_SECRET in .env")
    r = httpx.post(
        f"{API}/oauth/token",
        auth=(cid, secret),
        data={"grant_type": "client_credentials"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def is_sdd(subj: dict) -> bool:
    name = ((subj.get("tvrtka") or {}).get("ime") or "").lower()
    return "sportsk" in name and "dioni" in name


def fetch_subject(client: httpx.Client, oib: str, refresh: bool) -> dict | None:
    cache = CACHE / f"{oib}.json"
    if cache.exists() and not refresh:
        txt = cache.read_text()
        return json.loads(txt) if txt.strip() else None
    for attempt in range(4):
        try:
            r = client.get(
                f"{API}/javni/detalji_subjekta",
                params={
                    "expand_relations": "true",
                    "tip_identifikatora": "oib",
                    "identifikator": oib,
                },
                timeout=30,
            )
            if r.status_code in (400, 404):
                # 404 = OIB is not a company (udruga); 400 = malformed/invalid OIB
                cache.write_text("")
                return None
            if r.status_code == 200:
                cache.write_text(r.text)
                time.sleep(0.1)
                return r.json()
            log.warning("HTTP %s for oib=%s (try %d)", r.status_code, oib, attempt + 1)
        except (httpx.HTTPError, ValueError) as e:
            log.warning("err oib=%s: %s (try %d)", oib, e, attempt + 1)
        time.sleep(0.6 * (attempt + 1))
    return None


def ensure_columns(conn) -> None:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(clubs)").fetchall()}
    spec = {
        "sudreg_mbs": "TEXT",
        "pravni_oblik": "TEXT",
        "is_sdd": "INTEGER",
        "temeljni_kapital": "INTEGER",
        "temeljni_kapital_valuta": "TEXT",
    }
    for col, typ in spec.items():
        if col not in cols:
            conn.execute(f"ALTER TABLE clubs ADD COLUMN {col} {typ}")
            log.info("added column %s", col)


def run(limit: int | None, refresh: bool, workers: int) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    token = get_token()
    log.info("sudreg token OK")

    with connect() as conn:
        ensure_columns(conn)
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT id, canonical_name, oib, email FROM clubs "
                "WHERE oib IS NOT NULL AND oib != '' ORDER BY id"
            ).fetchall()
        ]
        if not refresh:
            rows = [r for r in rows if r.get("sudreg_mbs") is None]
        if limit:
            rows = rows[:limit]
        log.info("clubs to query: %d", len(rows))

        client = httpx.Client(
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            http2=False,
        )

        def work(club: dict):
            return club, fetch_subject(client, club["oib"], refresh)

        results = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(work, c) for c in rows]
            for i, f in enumerate(as_completed(futs), 1):
                results.append(f.result())
                if i % 100 == 0:
                    log.info("queried %d/%d", i, len(rows))
        client.close()

        stat = {"company": 0, "sdd": 0, "not_company": 0, "email": 0}
        sdd_names = []
        for club, subj in results:
            if subj is None:
                stat["not_company"] += 1
                continue
            stat["company"] += 1
            po = (subj.get("pravni_oblik") or {}).get("vrsta_pravnog_oblika") or {}
            sdd = is_sdd(subj)
            if sdd:
                stat["sdd"] += 1
                sdd_names.append(club["canonical_name"])
            kap = (subj.get("temeljni_kapitali") or [{}])[-1]
            iznos = kap.get("iznos")
            valuta = (kap.get("valuta") or {}).get("naziv")

            sets = ["sudreg_mbs=?", "pravni_oblik=?", "is_sdd=?",
                    "temeljni_kapital=?", "temeljni_kapital_valuta=?"]
            vals = [str(subj.get("potpuni_mbs") or subj.get("mbs")),
                    po.get("naziv"), 1 if sdd else 0, iznos, valuta]

            emails = subj.get("email_adrese") or []
            if emails and not (club.get("email") or "").strip():
                em = (emails[0].get("adresa") or "").strip().lower()
                if EMAIL_RE.match(em):
                    sets.append("email=?"); vals.append(em); stat["email"] += 1

            vals.append(club["id"])
            conn.execute(f"UPDATE clubs SET {', '.join(sets)} WHERE id=?", vals)
        conn.commit()

        log.info(
            "sudreg done | company=%d (s.d.d.=%d) not_company=%d | email filled=%d",
            stat["company"], stat["sdd"], stat["not_company"], stat["email"],
        )
        if sdd_names:
            log.info("s.d.d. clubs: %s", ", ".join(sorted(sdd_names)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    run(a.limit, a.refresh, a.workers)
