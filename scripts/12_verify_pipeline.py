"""E2E pipeline verifier.

Samples a stratified random set of clubs and produces verifier prompts for
parallel Claude Code subagents to audit. After agents return JSON results,
aggregates into a 0-100 reliability score per dimension and overall.

Usage:

  # 1. Generate batched prompts (e.g. 3 batches of 5 = 15 clubs total)
  uv run python scripts/12_verify_pipeline.py prompts --n 15 --batches 3 \\
      --out data/verification/run-YYYY-MM-DD/

  # 2. Run each batch as a Claude Code subagent ("general-purpose" type).
  #    Paste the contents of the corresponding batch_*.md as the prompt.
  #    Save each agent's RESULTS JSON block into batch_*.json.

  # 3. Aggregate the JSON results into a reliability report.
  uv run python scripts/12_verify_pipeline.py aggregate \\
      data/verification/run-YYYY-MM-DD/

Stratification (default 15 clubs):
  T1: 3, T3: 2, T4: 2, T5: 2, T6: 3, T7: 2, T8: 1
(Tier 2 is sparse and overlaps T3 in practice; skipped by default.)

Sample seed defaults to 42 for reproducibility — pass --seed for variants.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402

DEFAULT_STRATA: list[tuple[int, int]] = [
    (1, 3), (3, 2), (4, 2), (5, 2), (6, 3), (7, 2), (8, 1),
]

DIMENSIONS = ("identity", "location", "contact", "phone_kind", "coordinates", "league")

METHODOLOGY = """== METHODOLOGY ==

For each club, score these 6 dimensions on {0.0, 0.5, 1.0}, or `null` when there
is nothing to verify (e.g. no phone, no coordinates):

1. **identity** — Is canonical_name a real Croatian football club currently or
   recently active? (1=clearly yes, 0=no/doesn't exist, 0.5=ambiguous)
2. **location** — Do `city` and `county` match where the club actually plays?
   Edge case: clubs playing home games at a different city's stadium during
   renovations (e.g. HNK Vukovar 1991 → Osijek) — count as correct.
3. **contact** — For each populated email/phone/website/fb_url/ig_url, verify
   it really belongs to THIS club. Red flags: aggregator sites
   (hrvatskekarta.com, poslovna.hr, companywall.hr), HNS Semafor profile pages
   (semafor.hns.family treated as fallback only if no club's own site),
   Facebook share links (facebook.com/sharer/), Twitter share buttons
   (twitter.com/share?), county-FA emails (nszz@, nssmz@), local news sites.
   1.0 all clean / 0.0 any clear leak / 0.5 mixed.
4. **phone_kind** — Croatian mobile prefixes after stripping leading 0: 91, 92,
   93, 95, 97, 98, 99. Anything else = landline. "unknown" correct when phone
   is malformed or non-Croatian.
5. **coordinates** — Are lat,lng within ~5 km of where the club actually plays?
   Cross-check via OSM. Croatia bounds: lat 42.0-46.6, lng 13.0-19.5.
6. **league** — Is the club currently in the listed league/tier? Check
   hns.family or county FA sites.

Cap web searches at ~3 per club. Use WebSearch + WebFetch. If a dimension is
genuinely undecidable, mark 0.5 with a brief explanation.

== OUTPUT FORMAT ==

Finish your response with EXACTLY this JSON block (parseable; one object per
club, no extra prose after the closing `]`):

RESULTS:
[
  {
    "slug": "...",
    "scores": {"identity": 1.0, "location": 1.0, "contact": 1.0,
               "phone_kind": 1.0, "coordinates": 1.0, "league": 1.0},
    "overall": 1.0,
    "issues": "short comma-separated description of any problems found",
    "evidence": ["url1", "url2"]
  }
]

`overall` = mean of non-null dimension scores."""


def sample_clubs(seed: int, strata: list[tuple[int, int]]) -> list[dict]:
    rng = random.Random(seed)
    with connect() as conn:
        out: list[dict] = []
        for tier, n in strata:
            rows = conn.execute(
                """
                SELECT DISTINCT c.* FROM clubs c
                JOIN club_seasons cs ON cs.club_id = c.id
                JOIN leagues l ON l.id = cs.league_id
                WHERE l.tier = ?
                ORDER BY c.canonical_name
                """,
                (tier,),
            ).fetchall()
            rows = [dict(r) for r in rows]
            if len(rows) > n:
                rows = rng.sample(rows, n)
            for r in rows:
                r["_tier"] = tier
                league_rows = conn.execute(
                    "SELECT l.name, l.tier, cs.season FROM club_seasons cs "
                    "JOIN leagues l ON l.id = cs.league_id WHERE cs.club_id = ?",
                    (r["id"],),
                ).fetchall()
                r["_leagues"] = [dict(x) for x in league_rows]
                out.append(r)
    return out


def format_club(c: dict) -> str:
    leagues = "; ".join(
        f"T{l['tier']}: {l['name']} ({l['season']})" for l in c["_leagues"]
    )
    lines = [f"CLUB: {c['canonical_name']} (slug={c['slug']}, tier={c['_tier']})"]
    fields = [
        "city", "county", "address", "phone", "phone_kind", "phone_e164",
        "email", "website", "fb_url", "ig_url", "x_url", "president",
        "stadium_name", "stadium_capacity", "founded_year", "lat", "lng",
    ]
    for k in fields:
        v = c.get(k)
        if v not in (None, "", 0):
            lines.append(f"  {k}: {v}")
    if leagues:
        lines.append(f"  leagues: {leagues}")
    return "\n".join(lines)


def cmd_prompts(args: argparse.Namespace) -> None:
    strata = list(DEFAULT_STRATA)
    if args.n != 15:
        # Scale strata proportionally if user overrides.
        total = sum(n for _, n in DEFAULT_STRATA)
        strata = [(t, max(1, round(n * args.n / total))) for t, n in DEFAULT_STRATA]
    clubs = sample_clubs(args.seed, strata)
    print(f"Sampled {len(clubs)} clubs.")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Split into N batches, round-robin so each batch has varied tiers.
    batches: list[list[dict]] = [[] for _ in range(args.batches)]
    for i, c in enumerate(clubs):
        batches[i % args.batches].append(c)

    labels = "ABCDEFGHIJ"
    for i, batch in enumerate(batches):
        if not batch:
            continue
        label = labels[i]
        body = "\n\n".join(format_club(c) for c in batch)
        prompt = (
            "You are auditing the data quality of a Croatian football clubs "
            "database. Use WebSearch + WebFetch to verify each field per the "
            "rubric below.\n\n"
            + METHODOLOGY
            + "\n\n== CLUBS TO VERIFY ==\n\n"
            + body
            + "\n"
        )
        (out_dir / f"batch_{label}.md").write_text(prompt)

    sample_meta = {
        "seed": args.seed,
        "strata": strata,
        "batches": args.batches,
        "clubs": [{"slug": c["slug"], "tier": c["_tier"], "batch": labels[i % args.batches]}
                  for i, c in enumerate(clubs)],
    }
    (out_dir / "sample.json").write_text(
        json.dumps(sample_meta, ensure_ascii=False, indent=2)
    )
    print(f"Wrote {len(batches)} batch prompt(s) + sample.json to {out_dir}")
    print(
        "\nNext: open each batch_*.md, run it as a general-purpose Claude Code "
        "subagent, save each RESULTS JSON block into batch_X.json (same dir)."
    )


def cmd_aggregate(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        raise SystemExit(f"directory missing: {run_dir}")

    all_results: list[dict] = []
    for path in sorted(run_dir.glob("batch_*.json")):
        data = json.loads(path.read_text())
        if isinstance(data, list):
            all_results.extend(data)
        elif isinstance(data, dict) and "results" in data:
            all_results.extend(data["results"])

    if not all_results:
        raise SystemExit(f"no batch_*.json results in {run_dir}")

    n = len(all_results)
    overall_avg = statistics.mean(r["overall"] for r in all_results)
    dim_avgs: dict[str, float | None] = {}
    for d in DIMENSIONS:
        vals = [r["scores"][d] for r in all_results if r["scores"].get(d) is not None]
        dim_avgs[d] = statistics.mean(vals) if vals else None

    report = {
        "run_date": date.today().isoformat(),
        "sample_size": n,
        "overall_score": round(overall_avg * 100, 1),
        "dimension_scores": {
            d: round(v * 100, 1) if v is not None else None
            for d, v in dim_avgs.items()
        },
        "per_club_results": all_results,
    }
    out_json = run_dir / "report.json"
    out_md = run_dir / "report.md"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    md = [
        f"# Pipeline verification report — {report['run_date']}",
        "",
        f"Sample size: **{n}** clubs (stratified by tier)",
        f"**Overall pipeline reliability: {report['overall_score']} / 100**",
        "",
        "## Dimension scores",
        "",
        "| Dimension | Score | Stars |",
        "|---|---:|---|",
    ]
    for d, v in report["dimension_scores"].items():
        if v is None:
            md.append(f"| {d} | n/a | — |")
        else:
            stars = "★" * int(round(v / 10))
            md.append(f"| {d} | {v} | {stars} |")
    md += ["", "## Per-club details", "",
           "| slug | tier | overall | issues |", "|---|---:|---:|---|"]
    sample_meta = json.loads((run_dir / "sample.json").read_text()) if (run_dir / "sample.json").exists() else {}
    tier_by_slug = {c["slug"]: c["tier"] for c in sample_meta.get("clubs", [])}
    for r in sorted(all_results, key=lambda x: -x["overall"]):
        tier = tier_by_slug.get(r["slug"], "?")
        md.append(f"| {r['slug']} | T{tier} | {r['overall']:.2f} | {r['issues'] or '—'} |")
    out_md.write_text("\n".join(md) + "\n")

    print(f"\nOVERALL: {report['overall_score']} / 100")
    print("Dimensions:")
    for d, v in report["dimension_scores"].items():
        print(f"  {d:<14} {v if v is not None else 'n/a'}")
    try:
        rel_json = out_json.relative_to(ROOT)
        rel_md = out_md.relative_to(ROOT)
    except ValueError:
        rel_json, rel_md = out_json, out_md
    print(f"\nWrote {rel_json} + {rel_md}")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("prompts", help="generate batched verifier prompts")
    pp.add_argument("--n", type=int, default=15, help="total clubs to sample")
    pp.add_argument("--batches", type=int, default=3, help="number of parallel batches")
    pp.add_argument("--seed", type=int, default=42)
    pp.add_argument("--out", required=True, help="output dir, e.g. data/verification/run-2026-05-17/")
    pp.set_defaults(func=cmd_prompts)

    pa = sub.add_parser("aggregate", help="aggregate batch_*.json into a report")
    pa.add_argument("run_dir", help="directory containing batch_*.json files")
    pa.set_defaults(func=cmd_aggregate)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
