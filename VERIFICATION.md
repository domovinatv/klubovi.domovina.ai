# Pipeline verification — methodology

Croatian football clubs DB is built by deterministic scripts (SofaScore ingest →
hrnogomet ingest → Firecrawl backfill → Nominatim geocoding) plus some manual
fix-ups. None of those steps tell you whether the resulting fields are *right*.
This file describes the AI-driven sampling audit that does.

## Goal

For a random stratified sample of clubs, score the data **a generic Claude
subagent with web access would give** if asked to verify each field. Aggregate
into a per-dimension reliability score plus an overall 0-100 pipeline score.

The goal is to catch **systemic data-quality regressions** (e.g. "30% of
amateur clubs now have aggregator URLs as their website"), not individual bad
rows. Sample size is small on purpose — speed of feedback trumps statistical
significance at this volume.

## Sample size and stratification

Default sample: **15 clubs** across tiers:

| Tier        |  N |
|-------------|---:|
| T1 (HNL)    |  3 |
| T3 (2. NL)  |  2 |
| T4 (3. NL)  |  2 |
| T5 (4. NL)  |  2 |
| T6 (1. ŽNL) |  3 |
| T7 (2. ŽNL) |  2 |
| T8 (3. ŽNL) |  1 |

T2 (1. NL) is skipped by default — it overlaps T3 in practice and has only ~12
clubs total. Override via `--n`.

`random.Random(seed)` with `--seed 42` by default → re-runs hit the same
sample. Pass `--seed N` for an independent draw.

## Dimensions scored per club

Each club is scored on six dimensions, each on the scale **{0.0, 0.5, 1.0}** or
`null` when the field is empty:

| # | Dimension      | What's being verified |
|---|----------------|------------------------|
| 1 | **identity**   | Is the canonical_name a real Croatian football club, currently or recently active? |
| 2 | **location**   | Do `city`/`county` match where the club actually plays? Allowance for relocated-home cases (e.g. Vukovar 1991 playing in Osijek). |
| 3 | **contact**    | Are populated email/phone/website/fb_url/ig_url really this club's? Per-field judgement aggregated to one score. |
| 4 | **phone_kind** | Is the mobile/landline/unknown classification correct per HAKOM mobile prefixes (091/092/093/095/097/098/099)? |
| 5 | **coordinates**| Are lat/lng within ~5 km of the actual home field/village? |
| 6 | **league**     | Is the listed current league/tier accurate? |

`overall` = mean of non-null dimensions for that club.
**Pipeline score** = mean(`overall`) × 100 across all sampled clubs.
**Per-dimension reliability** = mean(score) × 100 across clubs where that
dimension was scoreable.

## How the verification runs

1. **Sample + prompt generation** (deterministic, no external calls):
   ```
   uv run python scripts/12_verify_pipeline.py prompts \
       --n 15 --batches 3 --seed 42 \
       --out data/verification/run-YYYY-MM-DD/
   ```
   This writes `batch_A.md`, `batch_B.md`, `batch_C.md`, and `sample.json`
   into the run directory. Each `batch_*.md` is a fully-formed prompt with
   the methodology rubric and one club per N-th club.

2. **Audit execution** (parallel general-purpose subagents, manual today):
   Paste each `batch_*.md` into a Claude Code session and run it as a
   `general-purpose` subagent with `WebSearch` + `WebFetch` allowed. Each
   agent caps itself at ~3 searches per club and returns a JSON `RESULTS:`
   block at the end of its response.

   Save each agent's JSON array into the same run directory as
   `batch_A.json`, `batch_B.json`, ... (the script doesn't enforce the
   schema; it trusts the agents).

3. **Aggregation** (deterministic):
   ```
   uv run python scripts/12_verify_pipeline.py aggregate \
       data/verification/run-YYYY-MM-DD/
   ```
   Produces `report.json` and `report.md` summarising the per-dimension
   scores, the overall pipeline number, and a per-club table sorted by
   `overall` (descending).

## Reading the report

A passing run looks like ≥ 90 overall with no single dimension under 70. Lower
numbers point at the systemic gaps:

- **identity < 90** → ingest is pulling in clubs that don't exist or
  duplicate-resolving wrongly. Check `club_aliases` and the disambiguation
  prefix logic (`_PAREN_RE` in `src/backfill.py`).
- **location < 90** → SofaScore is putting clubs in the wrong city, or
  `03_enrich_counties.py` is mis-mapping `countyId`. Sanity-check the
  county_leagues filter.
- **contact < 80** → the Firecrawl backfill is leaking data from aggregators,
  county FAs, or non-club news sites. Update the blocklist in
  `src/backfill.py` (`score_url`, `_FA_EMAIL_RE`).
- **coordinates < 90** → Nominatim resolved to a county centroid or wrong
  village. Improve `_name_place_candidates` / `_addr_tail` in
  `scripts/10_geocode_nominatim.py`.
- **league < 95** → the league table didn't refresh after a season change.
  Re-run `scripts/01_ingest_sofascore.py` + `scripts/02_ingest_hrnogomet.py`.

## What the audit naturally surfaces

Beyond a score, the agents leave **evidence URLs** in each club's record.
Those URLs are often canonical sources (HNS Semafor club pages, Wikipedia
articles, Transfermarkt entries, county FA listings) that the deterministic
backfill never visited. The follow-up move is to mine `evidence` URLs from
recent runs as new search candidates for the next backfill pass, or as direct
sources of corrected fields.

In our **2026-05-17 baseline run** (overall 92.0/100) the audit identified:

- Crikvenica's `stadium_name` is the club's own name (extracted text leaked).
- Bilogora 91 and Croatia (G) websites point at `semafor.hns.family` and
  `hrvatskekarta.com` (aggregator); fb/x are share-button URLs.
- Dinamo (O) inherited the entire county-FA contact block (`nssmz`).
- Rugvica Sava's website / FB / IG all point at `dugoselska-kronika.hr` — a
  local-news outlet, not the club.

Those five clubs are the actionable cleanup queue for the next iteration.

## Re-running and versioning

Each run gets its own `data/verification/run-YYYY-MM-DD/` directory and is
checked in (small — `~30 KB` per run). Comparing two `report.json` files shows
whether changes between runs lifted or hurt specific dimensions. The
`per_club_results[].issues` strings are the most useful diff signal.

## Time series

| Run | Overall | identity | location | contact | phone_kind | coordinates | league | What changed since previous |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| **2026-05-17** (baseline) | 92.0 | 96.7 | 100 | 70.0 | 100 | 90.0 | 100 | first measurement after the 901-club backfill landed |
| **2026-05-17b** | 93.0 | 100 | 100 | **75.0** | 100 | 86.7 | 100 | `scripts/14_cleanup_leaks.py` (~800 leaky values nulled), `src/backfill.py` blocklist expanded, 654-club targeted re-backfill |

Run 2 caveats:

- **Contact moved 70 → 75** — real lift, but smaller than projected. Cleanup
  cleared known leaks (aggregator URLs, share-button links, FA cross-contamination,
  cross-club shared values), but the targeted re-backfill surfaced *new* leak
  classes the original blocklist didn't anticipate:
  - **Sister-club cross-contamination** — NK Dinamo Odra inherited HNK Segesta
    Sisak's website + email. Same Sisak area, different clubs. No URL pattern
    catches this; needs name-vs-domain similarity check.
  - **Town/city portal as `website`** — NK Bilogora 91's website became
    `grubisnopolje.hr` (the town's city-government portal). Not an aggregator
    and not a club site either.
  - **Local-news domain variants** — we blocked `dugoselska-kronika.hr` but
    the re-backfill found `dugoselski-sport.hr` for Rugvica Sava — same
    publisher, different domain.

- **Coordinates regressed 90 → 86.7** — *same lat/lng* in DB, scored more
  strictly this time. Run 2 agents caught two Nominatim village-centroid
  errors (Croatia-G 19 km off Grabrovnica, Dinamo-O 22 km off Odra Sisačka)
  that Run 1 agents accepted. Not a data regression, a measurement-tightening.
  Indicates the audit is internally inconsistent on the `~5 km` threshold —
  rubric should be sharpened with a deterministic distance check before the
  next run.

The three new contact-leak patterns are the right input for the next
iteration's blocklist + heuristic rules.
