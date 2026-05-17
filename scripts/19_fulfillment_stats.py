"""Per-club fulfillment / completeness report.

Treats the DB as a contact-outreach asset and asks:
  "for each club, how many of the N target fields are filled?"
  "what % of clubs reach which completeness level?"

The target field set is the union of every column needed for the
outreach product (SMS / email / postal / online), grouped by usefulness:

  Identity (always filled by ingest, weight = 0):
    canonical_name, slug, city, county
  Geo (geocoded to 100%, weight = 1 collectively):
    lat+lng                                    -> "located"
  Reachable channels (the actual outreach surface, weight = 1 each):
    phone_e164      -> "callable"
    has_mobile      -> "smsable"  (phone_kind == 'mobile')
    email           -> "emailable"
    address         -> "mailable"
    website         -> "online"
    fb_url          -> "fb"
    ig_url          -> "ig"
  Metadata (nice to have, weight = 0.5 each):
    stadium_name, founded_year, president, semafor_url, sofascore_url

Outputs:
  - data/exports/fulfillment_per_club.csv  — one row per club + score
  - stdout: distribution histogram by tier and overall, plus the
            estimate of how many clubs are at each "outreach-readiness"
            tier (4-channel, 3-channel, ...)

Usage:
  uv run python scripts/19_fulfillment_stats.py
"""
from __future__ import annotations

import csv
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fulfillment")

OUT_CSV = ROOT / "data" / "exports" / "fulfillment_per_club.csv"


REACHABLE_FIELDS = [
    ("callable",  "phone_e164 IS NOT NULL"),
    ("smsable",   "phone_e164 IS NOT NULL AND phone_kind = 'mobile'"),
    ("emailable", "email IS NOT NULL"),
    ("mailable",  "address IS NOT NULL"),
    ("online",    "website IS NOT NULL"),
    ("fb",        "fb_url IS NOT NULL"),
    ("ig",        "ig_url IS NOT NULL"),
]

METADATA_FIELDS = [
    ("stadium",       "stadium_name IS NOT NULL"),
    ("founded",       "founded_year IS NOT NULL"),
    ("president",     "president IS NOT NULL"),
    ("semafor_url",   "semafor_url IS NOT NULL"),
    ("sofascore_url", "sofascore_url IS NOT NULL"),
]


def fetch_rows(conn) -> list[dict]:
    cols = ", ".join(
        ["id", "canonical_name", "slug", "city", "county"]
        + [
            f"({sql}) AS {name}"
            for name, sql in REACHABLE_FIELDS + METADATA_FIELDS
        ]
        + ["(SELECT GROUP_CONCAT(DISTINCT 'T' || l.tier) FROM club_seasons cs "
           "JOIN leagues l ON l.id = cs.league_id WHERE cs.club_id = clubs.id) AS tiers"]
    )
    return [dict(r) for r in conn.execute(f"SELECT {cols} FROM clubs").fetchall()]


def primary_tier(tiers: str | None) -> str:
    """Return the lowest-numbered (= highest competition) tier string."""
    if not tiers:
        return "T?"
    parts = sorted({t for t in tiers.split(",") if t}, key=lambda t: int(t.lstrip("T") or "99"))
    return parts[0] if parts else "T?"


def score_row(row: dict) -> tuple[int, int, float]:
    """Return (reachable_count, metadata_count, weighted_score 0..1)."""
    reach = sum(1 for name, _ in REACHABLE_FIELDS if row[name])
    meta = sum(1 for name, _ in METADATA_FIELDS if row[name])
    located = 1  # 100% geocoded, treat as constant
    # Weighted: 1 per reachable channel (max 7), 0.5 per metadata (max 2.5),
    # +1 for located. Max raw = 7 + 2.5 + 1 = 10.5. Normalize to 0..1.
    raw = reach + meta * 0.5 + located
    return reach, meta, raw / 10.5


def run() -> None:
    with connect() as conn:
        rows = fetch_rows(conn)

    # Write per-club CSV.
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        cw = csv.writer(f)
        cw.writerow([
            "id", "tier", "canonical_name", "city", "county",
            *(name for name, _ in REACHABLE_FIELDS),
            *(name for name, _ in METADATA_FIELDS),
            "reachable_count", "metadata_count", "score_pct",
        ])
        for r in rows:
            t = primary_tier(r["tiers"])
            reach, meta, score = score_row(r)
            cw.writerow([
                r["id"], t, r["canonical_name"], r["city"] or "", r["county"] or "",
                *(int(bool(r[name])) for name, _ in REACHABLE_FIELDS),
                *(int(bool(r[name])) for name, _ in METADATA_FIELDS),
                reach, meta, round(score * 100, 1),
            ])
    log.info("wrote %d rows to %s", len(rows), OUT_CSV)

    # Console: overall distribution + per-tier.
    by_tier: dict[str, list[tuple[int, int, float]]] = defaultdict(list)
    overall: list[tuple[int, int, float]] = []
    for r in rows:
        s = score_row(r)
        overall.append(s)
        by_tier[primary_tier(r["tiers"])].append(s)

    def fmt_dist(scores: list[tuple[int, int, float]]) -> str:
        n = len(scores)
        if not n:
            return "n=0"
        reach = Counter(s[0] for s in scores)
        bins = [0, 0, 0, 0, 0]  # 0 / 1 / 2 / 3 / 4+
        for c in reach:
            idx = min(c, 4)
            bins[idx] += reach[c]
        return (
            f"n={n}  "
            f"0ch={bins[0]:>3}  "
            f"1ch={bins[1]:>3}  "
            f"2ch={bins[2]:>3}  "
            f"3ch={bins[3]:>3}  "
            f"4ch+={bins[4]:>3}  "
            f"mean_score={sum(s[2] for s in scores) / n * 100:.1f}%"
        )

    print()
    print("OVERALL  ", fmt_dist(overall))
    print()
    print("PER TIER:")
    for t in sorted(by_tier, key=lambda t: int(t.lstrip("T") or "99")):
        print(f"  {t:>3}  {fmt_dist(by_tier[t])}")

    # Outreach-readiness buckets — actionable framing for SMS/email/postal/online.
    print()
    print("OUTREACH READINESS (any-one-channel = reachable at all):")
    bucket_labels = [
        ("SMS-ready", lambda r: r["smsable"]),
        ("Callable (mobile OR landline)", lambda r: r["callable"]),
        ("Emailable", lambda r: r["emailable"]),
        ("Postal-mailable (have address)", lambda r: r["mailable"]),
        ("Online (website or FB)", lambda r: r["online"] or r["fb"]),
        ("4-channel (call+email+address+online)",
         lambda r: r["callable"] and r["emailable"] and r["mailable"]
                   and (r["online"] or r["fb"])),
        ("Zero channels (just on map)",
         lambda r: not any(r[n] for n, _ in REACHABLE_FIELDS)),
    ]
    for label, fn in bucket_labels:
        n = sum(1 for r in rows if fn(r))
        print(f"  {n:>3}  {label}")


if __name__ == "__main__":
    run()
