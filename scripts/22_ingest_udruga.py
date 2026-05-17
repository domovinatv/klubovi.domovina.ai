"""
Ingest Registar udruga data into the clubs table.

Source: data/raw/udruge/match_report.json + osobe.csv (joined on UDR_ID).

Idempotent fill rules:
- Only AKTIVAN matches write to columns we haven't filled yet. BRISAN/PRESTANAK
  matches still set udruga_id + registry_* so we can revisit, but we skip
  pulling president/address/etc. from stale records.
- For each writable column, only write when the existing value is NULL/empty.
  Never overwrite existing data.
- president: prefer SVOJSTVO containing "PREDSJEDNIK" over generic "OSOBA
  OVLAŠTENA ZA ZASTUPANJE"; fall back to the latter.

Outputs a before/after fill report.
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
csv.field_size_limit(sys.maxsize)

MATCHES = ROOT / "data" / "raw" / "udruge" / "match_report.json"
OSOBE = ROOT / "data" / "raw" / "udruge" / "osobe.csv"
DJEL = ROOT / "data" / "raw" / "udruge" / "djelatnosti.csv"
DB = ROOT / "data" / "clubs.db"


def title_case_name(first: str, last: str) -> str:
    def cap(token: str) -> str:
        if not token:
            return token
        if "-" in token:
            return "-".join(cap(p) for p in token.split("-"))
        return token[:1].upper() + token[1:].lower()
    parts = [cap(t) for t in (first or "").split()] + [cap(t) for t in (last or "").split()]
    return " ".join(p for p in parts if p)


def parse_year(date_str: str | None) -> int | None:
    if not date_str:
        return None
    m = re.search(r"(\d{4})", date_str)
    if not m:
        return None
    y = int(m.group(1))
    return y if 1850 <= y <= 2100 else None


def fields_before(conn: sqlite3.Connection) -> dict[str, int]:
    cols = ["president", "address", "founded_year", "email", "oib", "udruga_id",
            "registry_status"]
    out = {}
    for c in cols:
        q = f"SELECT COUNT(*) FROM clubs WHERE {c} IS NOT NULL AND {c} <> ''"
        out[c] = conn.execute(q).fetchone()[0]
    return out


def main(dry_run: bool = False):
    report = json.loads(MATCHES.read_text())
    matches = report["matched"]
    print(f"matches in report: {len(matches)}")

    # Load osobe.csv indexed by UDR_ID -> list of (rank, ime, prezime, funkcija, svojstvo)
    osobe_by_udr: dict[str, list] = defaultdict(list)
    with OSOBE.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            udr = row["UDR_ID"]
            if not udr:
                continue
            ime = (row["IME"] or "").strip()
            prez = (row["PREZIME"] or "").strip()
            svoj = (row["SVOJSTVO"] or "").strip().upper()
            funk = (row["FUNKCIJA"] or "").strip().upper()
            if "LIKVIDATOR" in svoj or "LIKVIDATOR" in funk:
                continue
            if not (ime or prez):
                continue
            # rank: lower = better (presidents first)
            rank = 99
            if "PREDSJEDNIK" in svoj or "PREDSJEDNIK" in funk:
                rank = 0
            elif "OSOBA OVLASTENA" in svoj or "OVLAŠTEN" in svoj:
                rank = 1
            elif "ZAMJENIK" in svoj or "DOPREDSJEDNIK" in svoj:
                rank = 2
            osobe_by_udr[udr].append((rank, ime, prez, svoj, funk))

    conn = sqlite3.connect(DB)
    before = fields_before(conn)
    print("BEFORE:", before)

    written = {"president": 0, "address": 0, "founded_year": 0, "email": 0,
               "oib": 0, "udruga_id": 0, "registry_status": 0}
    skipped_stale = 0
    aktivan_seen = 0

    for cid_str, m in matches.items():
        cid = int(cid_str)
        udr = m["udr_id"]
        status = m["status"]
        # Always set udruga_id + registry metadata (regardless of status) — it
        # documents the match. We just won't pull stale fields from BRISAN.
        registry_url = f"https://registri-npo-mpu.gov.hr/#!udruge/detalji/{udr}"
        updates = {
            "udruga_id": udr,
            "registry_status": status,
            "registry_naziv": m["naziv"],
            "registry_url": registry_url,
        }

        if status == "AKTIVAN":
            aktivan_seen += 1
            # OIB
            if m.get("oib"):
                updates["oib"] = m["oib"]
            # Address (only if empty)
            if m.get("sjediste"):
                updates["address_candidate"] = m["sjediste"]
            # Email (only if empty)
            if m.get("mail"):
                updates["email_candidate"] = m["mail"].strip()
            # Founded year
            yr = parse_year(m.get("datum_osn") or m.get("datum_upisa"))
            if yr:
                updates["founded_candidate"] = yr
            # President
            persons = osobe_by_udr.get(udr, [])
            if persons:
                persons.sort(key=lambda x: x[0])
                rank, ime, prez, svoj, funk = persons[0]
                role = svoj or funk or "OSOBA OVLAŠTENA ZA ZASTUPANJE"
                updates["president_candidate"] = title_case_name(ime, prez)
                updates["president_role"] = role
        else:
            skipped_stale += 1

        # Apply updates idempotently
        cur = conn.execute(
            "SELECT president, address, founded_year, email, oib, udruga_id, registry_status "
            "FROM clubs WHERE id=?", (cid,)
        ).fetchone()
        if cur is None:
            continue
        cur_pres, cur_addr, cur_fy, cur_email, cur_oib, cur_udr, cur_rs = cur

        sets = []
        vals = []
        # Always overwrite registry metadata to keep it fresh
        for col in ("udruga_id", "registry_status", "registry_naziv", "registry_url"):
            if col in updates:
                sets.append(f"{col}=?"); vals.append(updates[col])
        # Fill-only-if-empty fields
        if "oib" in updates and not cur_oib:
            sets.append("oib=?"); vals.append(updates["oib"]); written["oib"] += 1
        if "president_candidate" in updates and not (cur_pres or "").strip():
            sets.append("president=?"); vals.append(updates["president_candidate"]); written["president"] += 1
            if "president_role" in updates:
                sets.append("president_role=?"); vals.append(updates["president_role"])
        if "address_candidate" in updates and not (cur_addr or "").strip():
            sets.append("address=?"); vals.append(updates["address_candidate"]); written["address"] += 1
        if "founded_candidate" in updates and not cur_fy:
            sets.append("founded_year=?"); vals.append(updates["founded_candidate"]); written["founded_year"] += 1
        if "email_candidate" in updates and not (cur_email or "").strip():
            sets.append("email=?"); vals.append(updates["email_candidate"]); written["email"] += 1
        # Count udruga_id writes (always set, but count fresh)
        if not cur_udr:
            written["udruga_id"] += 1
        if not cur_rs:
            written["registry_status"] += 1

        sets.append("updated_at=CURRENT_TIMESTAMP")
        sql = f"UPDATE clubs SET {', '.join(sets)} WHERE id=?"
        vals.append(cid)
        if not dry_run:
            conn.execute(sql, vals)

    if not dry_run:
        conn.commit()
    after = fields_before(conn)
    print(f"\nAKTIVAN matches: {aktivan_seen}, skipped (BRISAN/PRESTANAK): {skipped_stale}")
    print("WRITTEN:", written)
    print("BEFORE:", before)
    print("AFTER: ", after)
    print("DELTA: ", {k: after[k] - before[k] for k in before})


if __name__ == "__main__":
    main(dry_run="--dry" in sys.argv)
