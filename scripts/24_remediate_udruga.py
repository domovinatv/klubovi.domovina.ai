"""
Roll back wrong udruga matches and re-apply the county-aware ones.

Context: scripts/22_ingest_udruga.py ran against v1 of the matcher (no county
gate). AI verification on a 32-club sample found ~34% of med-confidence matches
were wrong (wrong county / generic-name collision). v2 of the matcher adds a
hard county gate. This script reconciles the DB:

For each club:
  1. Old write target = v1 matched UDR_ID (if any)
  2. New write target = v2 matched UDR_ID (if any)
  3. If they agree → no-op.
  4. Else: for each pipeline-touched column (president, address, founded_year,
     oib, email), check if the current DB value matches what v1's ingest would
     have written. If so, the value is ours — clear it. Then apply v2's data
     with the same fill-if-empty rule.

Pre-existing original data (the 292 hand-curated presidents, the 686 manually-
collected addresses) is preserved: it doesn't match what v1 would have written,
so the clear step doesn't touch it.
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

DB = ROOT / "data" / "clubs.db"
OSOBE = ROOT / "data" / "raw" / "udruge" / "osobe.csv"
V1 = ROOT / "data" / "raw" / "udruge" / "match_report_v1.json"
V2 = ROOT / "data" / "raw" / "udruge" / "match_report.json"


def title_case_name(first: str, last: str) -> str:
    def cap(t: str) -> str:
        if not t:
            return t
        if "-" in t:
            return "-".join(cap(p) for p in t.split("-"))
        return t[:1].upper() + t[1:].lower()
    parts = [cap(t) for t in (first or "").split()] + [cap(t) for t in (last or "").split()]
    return " ".join(p for p in parts if p)


def parse_year(s: str | None) -> int | None:
    if not s:
        return None
    m = re.search(r"(\d{4})", s)
    if not m:
        return None
    y = int(m.group(1))
    return y if 1850 <= y <= 2100 else None


def load_osobe() -> dict[str, list]:
    by_udr: dict[str, list] = defaultdict(list)
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
            rank = 99
            if "PREDSJEDNIK" in svoj or "PREDSJEDNIK" in funk:
                rank = 0
            elif "OSOBA OVLASTENA" in svoj or "OVLAŠTEN" in svoj:
                rank = 1
            elif "ZAMJENIK" in svoj or "DOPREDSJEDNIK" in svoj:
                rank = 2
            by_udr[udr].append((rank, ime, prez, svoj, funk))
    return by_udr


def ingest_values(m: dict, osobe_by_udr: dict[str, list]) -> dict:
    """Return the {col: value} mapping v22 ingest would have produced from
    match m, for status=AKTIVAN. Same shape as scripts/22_ingest_udruga.py."""
    if m["status"] != "AKTIVAN":
        return {}
    out = {}
    if m.get("oib"):
        out["oib"] = m["oib"]
    if m.get("sjediste"):
        out["address"] = m["sjediste"]
    if m.get("mail"):
        out["email"] = m["mail"].strip()
    yr = parse_year(m.get("datum_osn") or m.get("datum_upisa"))
    if yr:
        out["founded_year"] = yr
    persons = osobe_by_udr.get(m["udr_id"], [])
    if persons:
        persons.sort(key=lambda x: x[0])
        rank, ime, prez, svoj, funk = persons[0]
        out["president"] = title_case_name(ime, prez)
        out["president_role"] = svoj or funk or "OSOBA OVLAŠTENA ZA ZASTUPANJE"
    return out


def main(dry_run: bool = False):
    v1 = json.loads(V1.read_text())["matched"]
    v2 = json.loads(V2.read_text())["matched"]
    osobe = load_osobe()
    print(f"v1 matches: {len(v1)}, v2 matches: {len(v2)}")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    stats = {
        "agree": 0, "changed": 0, "removed": 0, "added": 0, "noop": 0,
        "cleared": defaultdict(int),
        "rewritten": defaultdict(int),
    }

    all_cids = set(v1) | set(v2)
    for cid_str in all_cids:
        cid = int(cid_str)
        v1m = v1.get(cid_str)
        v2m = v2.get(cid_str)

        row = conn.execute(
            "SELECT id, president, president_role, address, founded_year, "
            "email, oib, udruga_id, registry_status FROM clubs WHERE id=?", (cid,)
        ).fetchone()
        if row is None:
            continue
        cur = dict(row)

        # Same UDR_ID in v1 and v2 -> no change.
        if v1m and v2m and v1m["udr_id"] == v2m["udr_id"]:
            stats["agree"] += 1; continue

        # Skip if the row's registry_status is SDD_COMPANYWALL — that's #23,
        # not part of this pipeline.
        if cur.get("registry_status") == "SDD_COMPANYWALL":
            continue

        if v1m and not v2m:
            stats["removed"] += 1
        elif v2m and not v1m:
            stats["added"] += 1
        else:
            stats["changed"] += 1

        # 1. Clear values written by v1 (only if current value still matches
        #    what v1's ingest would have written — protects originals).
        v1_vals = ingest_values(v1m, osobe) if v1m else {}
        sets, vals = [], []
        for col in ("president", "president_role", "address", "founded_year",
                    "email", "oib"):
            if col not in v1_vals:
                continue
            if cur.get(col) is None or cur.get(col) == "":
                continue
            # Only clear if the value is exactly what v1 would have written.
            # For president_role we just clear when president is being cleared.
            if col == "president_role":
                if "president" in v1_vals and cur.get("president") == v1_vals["president"]:
                    sets.append(f"{col}=NULL")
                    stats["cleared"][col] += 1
                continue
            if str(cur.get(col)).strip() == str(v1_vals[col]).strip():
                sets.append(f"{col}=NULL")
                stats["cleared"][col] += 1

        # 2. Apply v2 values fill-if-empty (use post-clear state).
        v2_vals = ingest_values(v2m, osobe) if v2m else {}
        # Recompute post-clear current values
        post = dict(cur)
        for s in sets:
            col = s.split("=")[0]
            post[col] = None
        for col in ("oib", "president", "address", "founded_year", "email"):
            if col not in v2_vals:
                continue
            if (post.get(col) or "") != "":
                continue
            sets.append(f"{col}=?"); vals.append(v2_vals[col]); stats["rewritten"][col] += 1
            if col == "president" and "president_role" in v2_vals:
                sets.append("president_role=?"); vals.append(v2_vals["president_role"])

        # 3. Always refresh registry_* metadata to the v2 match (or clear if
        #    v2 removed it).
        if v2m:
            url = f"https://registri-npo-mpu.gov.hr/#!udruge/detalji/{v2m['udr_id']}"
            sets.append("udruga_id=?"); vals.append(v2m["udr_id"])
            sets.append("registry_status=?"); vals.append(v2m["status"])
            sets.append("registry_naziv=?"); vals.append(v2m["naziv"])
            sets.append("registry_url=?"); vals.append(url)
        else:
            sets.append("udruga_id=NULL")
            sets.append("registry_status=NULL")
            sets.append("registry_naziv=NULL")
            sets.append("registry_url=NULL")

        if sets:
            sets.append("updated_at=CURRENT_TIMESTAMP")
            sql = f"UPDATE clubs SET {', '.join(sets)} WHERE id=?"
            vals.append(cid)
            if not dry_run:
                conn.execute(sql, vals)

    if not dry_run:
        conn.commit()
    print("\nstats:")
    for k, v in stats.items():
        print(f"  {k}: {dict(v) if isinstance(v, defaultdict) else v}")
    # Fulfillment after
    fields = ["president", "address", "founded_year", "email", "oib", "udruga_id"]
    print("\nAfter:")
    for f in fields:
        q = f"SELECT COUNT(*) FROM clubs WHERE {f} IS NOT NULL AND {f} <> ''"
        n = conn.execute(q).fetchone()[0]
        print(f"  {f}: {n} ({100*n/901:.1f}%)")


if __name__ == "__main__":
    main(dry_run="--dry" in sys.argv)
