# Hrvatski amaterski nogometni klubovi

Sustavna lokalna baza svih hrvatskih nogometnih klubova od SuperSport HNL-a do
3. županijske lige, s planiranim backfillom kontakt podataka po klubu.

## Trenutno stanje

901 klub iz 80 liga, idempotentno ingestano iz dva izvora.

| Tier | Razina                  | Klubova | Izvor          |
|-----:|-------------------------|--------:|----------------|
| 1    | SuperSport HNL          |      10 | SofaScore      |
| 2    | 1. NL                   |      12 | SofaScore      |
| 3    | 2. NL                   |      71 | SofaScore      |
| 4    | 3. NL (5 grupa)         |      80 | SofaScore      |
| 5    | 4. NL / MŽNL (6 grupa)  |      90 | hrnogomet.hr   |
| 6    | 1. ŽNL / Elitna ŽNL     |     287 | hrnogomet.hr   |
| 7    | 2. ŽNL                  |     324 | hrnogomet.hr   |
| 8    | 3. ŽNL                  |     101 | hrnogomet.hr   |

Pokrivenost polja: 100% `canonical_name`/`slug`, 75% `county`, 10% `city`,
`stadium_name`, `founded_year` (samo SofaScore-ovi). Kontakt polja (web, email,
telefon, FB/IG/X, predsjednik) još nisu popunjena — bit će Firecrawl backfill u
sljedećoj fazi.

## Izvori

**SofaScore** (`api.sofascore.com`) — pokriva tier 1-4. Zahtijeva Chrome TLS
fingerprint impersonation (`curl_cffi`); plain `httpx`/`requests` dobiju 403.
Tournament ID-jevi otkriveni preko `/category/14/unique-tournaments`. Team detail
endpoint daje stadion, kapacitet, godinu osnutka, grad.

**hrnogomet.hr** (`api.prod.hrnogomet.hr`) — pokriva sve županijske lige i 4.NL.
API ekstrahiran iz Flutter web bundle-a (`main.dart.js`). Bez prave autentikacije
— treba samo hardkodirani `x-hrnogomet-uuid` header + bogus Bearer token.
Endpointi `/county/leagues`, `/team-standings?shortname=X`, `/teams/{id}` su
javno dostupni; nacionalne lige preko `/leagues` traže JWT (out of scope).

## Layout

```
src/
  db.py             SQLite shema (clubs, club_aliases, leagues, club_seasons, backfill_runs)
  normalize.py      Slug i alias normalizacija (uključuje Hrvatske dijakritike đ/Đ)
  sofascore.py      API klijent (curl_cffi + chrome124 impersonate)
  hrnogomet.py      API klijent (httpx + extracted headers)

scripts/
  01_ingest_sofascore.py    Top 4 ranga + team detail
  02_ingest_hrnogomet.py    21 županija + 4. NL
  03_enrich_counties.py     /teams/{id} → countyId → clubs.county

data/
  clubs.db          SQLite baza (gitignored)
  raw/              JSON cache svih API odgovora (gitignored)
    sofascore/      po tournament_id / season_id
    hrnogomet/      county_leagues + standings/ + teams/
```

## Pokretanje

```bash
uv sync
uv run python scripts/01_ingest_sofascore.py
uv run python scripts/02_ingest_hrnogomet.py
uv run python scripts/03_enrich_counties.py
sqlite3 data/clubs.db "SELECT * FROM clubs LIMIT 5;"
```

Sve skripte su idempotentne — sirovi JSON je keširan u `data/raw/`, ponavljanje
poziva ne hita API ako je odgovor već lokalno spremljen.

## Firecrawl backfill

`scripts/04_backfill.py` per klubu radi search → URL scoring → JSON-schema
scrape sa Firecrawl v2 API-jem. API ključ se čita iz `.env`
(`FIRECRAWL_API_KEY`). Sve odgovore keširamo u `data/raw/firecrawl/`.

```bash
# Cijela županija
uv run python scripts/04_backfill.py --county "Zagrebačka županija"

# Po tier-u
uv run python scripts/04_backfill.py --tier 1 --tier 2

# Brzi pilot
uv run python scripts/04_backfill.py --limit 10
```

Pokriven dosad: Zagrebačka županija (47), Grad Zagreb (33), Splitsko-dalmatinska
(20). Po klubu prosječno **~6 credits**. Hit-rate na čistim runovima:
city/address ~50%, fb_url ~50%, email ~20-45%, phone ~20-55%, founded_year ~25%.

Quality guard-ovi u `src/backfill.py`:
- Blocklist aggregatora i FA-adresara (`.docx`/`poslovna.hr`/`nszz.hr`) koji
  cure tuđe podatke u extract
- FA email reject (`@nszz.hr`, `info@nszz`, savezi)
- Paren-disambig cross-club leak (HNK Hajduk (LB) ne smije pokupiti Split adresu)
- Social URL handling — Facebook se ne scrape-a (403), URL se zapisuje direktno

## Sljedeće faze

1. **City → county mapping** za 91 SofaScore klub (statički lookup, ~50 gradova).
2. **Scale-up backfill-a** na preostalih ~826 klubova (~5000 credits) — ili
   self-hosted Firecrawl stack ako se odlučimo izbjeći Cloud trošak.
3. **Coverage report** (`scripts/05_export.py`) — CSV + markdown po
   županiji/tier-u.
