# Hrvatski amaterski nogometni klubovi

Sustavna lokalna baza svih **901 hrvatskih nogometnih klubova** od SuperSport HNL-a
do 3. ŽNL — s kontakt podacima (web, email, telefon, predsjednik, društvene mreže),
adresama, stadionima, godinama osnutka, logotipima, i preciznim geo-koordinatama.

Cilj: alat za ciljani outreach (SMS, email, pošta) prema klubovima, s lokalnom
bazom koja se može ponovno generirati nuli kroz idempotentne skripte.

## Trenutno stanje

| Pokazatelj                                | Brojka            |
|-------------------------------------------|------------------:|
| Klubova ukupno                            | **901** (8 tier-ova)  |
| Backfill-ano (kroz Firecrawl)             | 896 (99.4%)       |
| Na karti s lat/lng                        | **901 (100%)**    |
| **Pipeline reliability** (AI audit)       | **93 / 100**      |
| **Pun kontakt** (telefon + email + adresa + online) | **155**     |
| Mobitela (SMS-ready, +385 E.164 format)   | 217               |
| Emaila                                    | 282               |
| Adresa                                    | 530               |
| Website                                   | 333               |
| FB profila                                | 410               |
| HNS Semafor profile linkova               | 172               |

| Tier | Razina                    | Klubova | Glavni izvor |
|-----:|---------------------------|--------:|--------------|
| 1    | SuperSport HNL            |      10 | SofaScore    |
| 2    | 1. NL                     |      12 | SofaScore    |
| 3    | 2. NL                     |      71 | SofaScore    |
| 4    | 3. NL (5 grupa)           |      80 | SofaScore    |
| 5    | 4. NL / MŽNL (6 grupa)    |      90 | hrnogomet.hr |
| 6    | 1. ŽNL / Elitna ŽNL       |     287 | hrnogomet.hr |
| 7    | 2. ŽNL                    |     324 | hrnogomet.hr |
| 8    | 3. ŽNL                    |     101 | hrnogomet.hr |

## Izvori podataka

### SofaScore (`api.sofascore.com`)
Pokriva top 4 tier-a. Zahtijeva **Chrome TLS fingerprint impersonation** (`curl_cffi`
s `impersonate="chrome124"`); plain `httpx`/`requests`/`curl` dobiju 403 zbog
Cloudflare anti-bot zaštite. Tournament ID-jevi otkriveni preko
`/category/14/unique-tournaments`. Team detail endpoint nosi **stadion, kapacitet,
godinu osnutka, grad, venue koordinate**.

### hrnogomet.hr (`api.prod.hrnogomet.hr`)
Pokriva **sve županijske lige + 4. NL**. API rekonstruiran iz Flutter web bundle-a
(`main.dart.js`). Bez prave autentikacije — treba samo hardkodirani
`x-hrnogomet-uuid: 8147731f-bf23-4f6e-9484-75b9b55c9a9a` header + bogus Bearer
token. Endpointi `/county/leagues`, `/team-standings?shortname=X`, `/teams/{id}`
javno dostupni; `/leagues` (nacionalne) traže JWT (skip).

### Firecrawl v2 (`api.firecrawl.dev`)
Search + LLM-driven JSON extraction iz klupskih stranica. **Multi-key auto-rotate**:
više `fc-...` ključeva u `FIRECRAWL_API_KEYS` env (comma-separated), klijent rotira
na 402/insufficient-credits i nastavlja na sljedećem.

### Nominatim + smart-fallback geocoder (`nominatim.openstreetmap.org`)
Besplatno, throttle 1.05 req/s. Per klub generira **ladder od 7-8 kandidata** od
najpreciznijeg do najopćenitijeg, zaustavlja se na prvom hit-u.

### Web research subagents (residual cases)
Za 15 klubova koje nijedan geocoder ne može — paralelni `general-purpose` agenti
s `WebSearch`/`WebFetch` ekstrahiraju lokaciju iz HNS Semafora, Wikipedije,
županijskih FA stranica.

## Pipeline po klubu

```
                ┌──────────────────────────────────────────────────────┐
                │   1. AKVIZICIJA (popunjavanje baze imena klubova)    │
                └──────────────────────────────────────────────────────┘

   ┌─────────────────────────┐         ┌──────────────────────────┐
   │ 01_ingest_sofascore.py  │         │ 02_ingest_hrnogomet.py   │
   │                         │         │                          │
   │ • TLS impersonate       │         │ • Static x-uuid header   │
   │   (curl_cffi chrome124) │         │ • /county/leagues        │
   │ • Top 4 tier (HNL→3.NL) │         │ • /team-standings        │
   │ • team detail → city,   │         │ • Tier 5-8 (4.NL + ŽNL)  │
   │   stadion, godina       │         │ • disambig "(K)" suffix  │
   └────────────┬────────────┘         └─────────────┬────────────┘
                │ 173 klubova                        │ 728 klubova
                └────────────────┬───────────────────┘
                                 ▼
                       ┌──────────────────┐
                       │  clubs (slug PK) │   ← 901 unique, 0 collisions
                       │  + club_aliases  │
                       │  + leagues       │
                       │  + club_seasons  │
                       └──────────────────┘
                                 │
                                 ▼
                ┌──────────────────────────────────────────┐
                │ 03_enrich_counties.py                    │
                │ • Za svaki klub: /teams/{id} → countyId  │
                │ • countyId → naziv iz county_leagues.json│
                │ • Filter: samo realne 21 županije        │
                │ • UPDATE clubs.county                    │
                └──────────────────────────────────────────┘

                ┌──────────────────────────────────────────────────────┐
                │   2. BACKFILL KONTAKATA (Firecrawl LLM extraction)   │
                └──────────────────────────────────────────────────────┘

                ┌──────────────────────────────────────────┐
                │ 04_backfill.py per klub:                 │
                │                                          │
                │ 1. Build search query:                   │
                │    "{ime} {grad/županija} kontakt"       │
                │ 2. /v2/search → 5 kandidata URL-ova      │
                │ 3. score_url() — preferira .hr,          │
                │    klupske domene, "kontakt" u path-u    │
                │    Penalizira: aggregatore (poslovna,    │
                │    companywall), FA adresare (nszz),     │
                │    docx/pdf, FB share linkove, pro-club  │
                │    domene za paren-disambig namesakes    │
                │ 4. Top URL:                              │
                │    • social? → samo zapiši FB/IG/X URL   │
                │    • inače → /v2/scrape s JSON schemom   │
                │ 5. Validate extracted:                   │
                │    • email regex + FA pattern reject     │
                │    • paren-disambig cross-club leak      │
                │      (npr. Hajduk-LB ne smije primiti    │
                │      Split adresu)                       │
                │ 6. UPSERT u clubs polja koja su prazna   │
                │ 7. INSERT u backfill_runs (audit)        │
                │                                          │
                │ Multi-key auto-rotate (5 ključeva):      │
                │   • 402 detect → switch & retry          │
                │   • Out-of-keys → graceful stop loop     │
                └──────────────────────────────────────────┘
                                 │
                                 ▼
                ┌─────────────────────┐
                │ 06_classify_phones  │   mobile/landline + E.164
                │ + auto on backfill  │   (091/092/093/095/097/098/099 = mob)
                └─────────────────────┘
                                 │
                                 ▼
                ┌──────────────────────────────────────────────────────┐
                │   3. GEOLOKACIJA (lat/lng za mapu)                   │
                └──────────────────────────────────────────────────────┘

   ┌──────────────────────────────────┐
   │ 09_geo_from_cache.py             │   67 klubova (top tier)
   │ • Scan data/raw/sofascore/teams  │   BESPLATNO, koristi cached
   │ • venueCoordinates → clubs.lat/lng│   API odgovore iz ingesta
   └─────────────────┬────────────────┘
                     │
                     ▼
   ┌────────────────────────────────────────────────┐
   │ 10_geocode_nominatim.py (smart fallback)       │   +819 klubova
   │                                                │
   │ Per klub, multi-candidate ladder:              │
   │   1. <address>, Hrvatska                       │
   │   2. <address tail> (zadnja 2 chunka)          │   84% pogodaka
   │   3. <ZIP>, Hrvatska         (5-znamenkasti)   │   ZIP-only carries
   │   4. <city>, <county>, Hrvatska                │
   │   5. <city>, Hrvatska                          │
   │   6. <place from name>, <county>               │   "NK Slavija Ivanovac"
   │   7. <place from name>, Hrvatska               │   → "Ivanovac"
   │   8. <last word>, <county>                     │
   │                                                │
   │ Throttle: 1.05 req/s (Nominatim ToS)           │
   │ Cache: SHA hash per query → 0 ponovljenih      │
   └────────────────┬───────────────────────────────┘
                    │
                    ▼
   ┌────────────────────────────────────────────────┐
   │ Manual subagent geocoding (web research)       │   +15 final klubova
   │                                                │
   │ 3 paralelna general-purpose subagent-a × 5     │
   │ Tools: WebSearch + WebFetch                    │
   │ Izvori: HNS Semafor, Wikipedia, county FA,     │
   │   sport-pozega, slobodna dalmacija, FB         │
   │ Output: lat/lng + confidence + source URL      │
   │ Validation: Croatia bounds 42-46.6 / 13-19.5   │
   │ Apply: data/manual_geocoding.sql               │
   └────────────────────────────────────────────────┘

                ┌──────────────────────────────────────────────────────┐
                │   4. ARTEFAKTI                                       │
                └──────────────────────────────────────────────────────┘

   ┌────────────────────────────┐  ┌────────────────────────────────┐
   │ 07_fetch_logos.py          │  │ 08_build_fts.py                │
   │ 901 PNG-a na disku         │  │ SQLite FTS5 virtualna tablica  │
   │ Servira /logos/{slug}.png  │  │ Dijakritike normalized         │
   └────────────────────────────┘  └────────────────────────────────┘

   ┌────────────────────────────┐  ┌────────────────────────────────┐
   │ 11_export_full_csv.py      │  │ web/app.py (FastAPI + HTMX)    │
   │ Read-only DB → CSV         │  │ /, /clubs/{}, /counties/{},    │
   │ ~/Desktop/...-YYYY-MM-DD   │  │ /leagues/{}, /map, /export.csv │
   └────────────────────────────┘  └────────────────────────────────┘
```

## Repozitorij

```
src/
  db.py             SQLite shema + helperi (upsert_club, upsert_league, ...)
  normalize.py      Slug + alias (uključuje Hrvatske dijakritike đ/Đ)
  phones.py         Mobile/landline klasifikator + E.164 normalizator
  sofascore.py      curl_cffi klijent + chrome124 impersonate
  hrnogomet.py      httpx klijent + extracted Flutter headers
  firecrawl.py      Multi-key klijent s auto-rotacijom + InsufficientCreditsError
  backfill.py       search → URL pick → scrape → validate → upsert + audit

scripts/
  01_ingest_sofascore.py      Top 4 ranga (HNL, 1.NL, 2.NL, 3.NL grupe)
  02_ingest_hrnogomet.py      21 županija + 4. NL (tier 5-8)
  03_enrich_counties.py       /teams/{id} → countyId → clubs.county
  04_backfill.py              Firecrawl backfill s filterima
  06_classify_phones.py       Migracija: phone_kind + phone_e164
  07_fetch_logos.py           Lokalno hrnogomet + SofaScore logoi
  08_build_fts.py             FTS5 indeks rebuild
  09_geo_from_cache.py        SofaScore venueCoordinates → lat/lng
  10_geocode_nominatim.py     Smart-fallback Nominatim geocoder
  11_export_full_csv.py       Read-only export DB → ~/Desktop/

web/
  app.py            FastAPI + Jinja2 + HTMX server
  templates/        base, index, club, county, league, map, partials/

data/
  clubs.db                Glavni SQLite (gitignored)
  raw/                    JSON cache po izvoru (gitignored)
    sofascore/            tournament_id / season / teams / team detail
    hrnogomet/            county_leagues + standings + teams
    firecrawl/            search + scrape per SHA-hash query
    nominatim/            geocode response per SHA-hash query
  logos/                  901 PNG-a (gitignored)
  manual_geocoding.sql    Idempotentni UPDATE-i za 15 web-researched klubova
```

## Pokretanje

```bash
# 1. Pripremi okolinu
uv sync

# 2. Akvizicija imena klubova (idempotentno, ~3-5 min)
uv run python scripts/01_ingest_sofascore.py
uv run python scripts/02_ingest_hrnogomet.py
uv run python scripts/03_enrich_counties.py

# 3. Firecrawl backfill (~$25-30 ako idemo cloud; multi-key auto-rotate)
#    .env: FIRECRAWL_API_KEYS=fc-...,fc-...
uv run python scripts/04_backfill.py --unprocessed
uv run python scripts/06_classify_phones.py

# 4. Logos + geo
uv run python scripts/07_fetch_logos.py
uv run python scripts/09_geo_from_cache.py
uv run python scripts/10_geocode_nominatim.py
sqlite3 data/clubs.db < data/manual_geocoding.sql   # 15 web-researched

# 5. Indeksi
uv run python scripts/08_build_fts.py

# 6. Web UI
uv run uvicorn web.app:app --port 8000
# → http://localhost:8000  (lista, search, filteri)
# → http://localhost:8000/map  (Leaflet karta, 901 marker)
# → http://localhost:8000/api/docs  (OpenAPI)

# 7. CSV snapshot
uv run python scripts/11_export_full_csv.py
# → ~/Desktop/hrvatski-nogometni-klubovi-YYYY-MM-DD.csv
```

Sve skripte su **idempotentne** — sirovi JSON je keširan u `data/raw/`,
ponavljanje poziva ne hita upstream API ako je odgovor već lokalno spremljen.

## Web aplikacija

Sve route:

| Route                          | Opis                                                |
|--------------------------------|-----------------------------------------------------|
| `GET /`                        | Lista s filterima (tier, županija, kontakt-tip, search) + paginacija |
| `GET /clubs/{slug}`            | Detail: kontakti, lige/sezone, aliasi, backfill povijest |
| `GET /counties/{name}`         | Per-županija pregled + stats hero + tier breakdown |
| `GET /leagues/{id}`            | Per-liga timovi                                    |
| `GET /map`                     | Leaflet karta s tier-color cluster markerima       |
| `GET /export.csv?...`          | CSV download honourirajući aktivne filtere         |
| `GET /api/stats`               | JSON global stats                                  |
| `GET /api/docs`                | OpenAPI                                            |

Kartice klubova pokazuju **reachability indikatore** u realnom vremenu:
`💬 SMS` / `📞 Poziv` / `✉ Email` / `📮 Pošta` / `🌐 Online` — obojano ako je
dostupno, faded ako nije. Lijevi rub kartice je **emerald → lime → amber → slate**
prema broju dostupnih kanala.

## Quality guards u backfill-u

`src/backfill.py` ima nekoliko zaštitnih mehanizama protiv tipičnih problema
LLM ekstrakcije:

1. **Aggregator blocklist** — `poslovna.hr`, `companywall.hr`, `sudreg.hr`,
   `fina.hr` cure podatke matične pravne osobe (npr. "HNK Hajduk d.d.")
   u svaki klub koji se zove "Hajduk".
2. **FA adresar blocklist** — `nszz.hr`, `.docx`/`.pdf`/`.xlsx` često
   sadrže više klubova u istom dokumentu i LLM uzima krivi red.
3. **FA email reject pattern** — `@nszz.hr`, `info@nszz`, `*@savez.*` su
   emailovi županijskih saveza, ne klubova.
4. **Paren-disambig cross-club leak** — kad klub ima `(LB)`/`(K)` suffix
   (npr. "HNK Hajduk (LB)") i extracted city/address ne sadrži klubovu
   županiju, ekstrakcija se odbacuje. Sprječava da podaci HNK Hajduk Split
   iscure u Bjelovarskog Hajduka.
5. **Social URL handling** — Facebook scrape vraća 403; URL se direktno
   zapisuje kao `fb_url` bez scrape-a. Sharer/dialog linkovi se filtriraju.
6. **Multi-key credit rotacija** — `InsufficientCreditsError` automatski
   prebacuje na sljedeći Firecrawl ključ.

## Manual geocoding za rezidualne klubove

15 klubova koje nijedan geocoder ne može (akronimi, raseljene zajednice,
kulturno-povijesni nazivi):

- `data/manual_geocoding.sql` — idempotentni UPDATE-i s adnotacijama i izvorima
  (HNS Semafor, Wikipedija, lokalni mediji)
- Primjeri: `NK Tomislav Siž` → Sveti Ivan Žabno (SIŽ = inicijali),
  `NK Vatrogasac (K)` → Kobilić, `NK Janjevo` → Kistanje (raseljeni Janjevci),
  `NK Rusin` → Mikluševci (rusinska manjina).

## Schema

```sql
clubs (id, slug PK, canonical_name, short_name, city, county, founded_year,
       stadium_name, stadium_capacity, website, email, phone, address,
       fb_url, ig_url, x_url, president, notes,
       phone_kind, phone_e164, lat, lng,
       created_at, updated_at)

club_aliases (alias_id PK, club_id FK, alias, source)
   sources: 'sofascore', 'hrnogomet', 'hrnogomet-id', 'sofascore-id'

leagues (id PK, name, tier, parent_id, county, sofascore_tournament_id)

club_seasons (club_id, league_id, season, source)  -- PK (club_id, league_id, season)

backfill_runs (run_id PK, club_id FK, ran_at, fields_filled JSON,
               source_urls JSON, raw_dump_path)

clubs_fts (FTS5 virtual)
   indexed: slug, name, short_name, city, address, aliases
   tokenizer: unicode61 remove_diacritics 2  +  pre-stripped đ/Đ
```

## AI-driven verification

`scripts/12_verify_pipeline.py` + `VERIFICATION.md` — stratified random sample
(default 15 clubs) verified by parallel general-purpose subagents on 6
dimensions (identity, location, contact, phone_kind, coordinates, league).
Aggregated to a per-dimension and overall 0-100 reliability score. Each run
goes into `data/verification/run-YYYY-MM-DD/`.

Current baseline: **93 / 100** (after one cleanup + re-backfill iteration —
`scripts/14_cleanup_leaks.py` cleared ~800 leaky values; expanded blocklist
in `src/backfill.py` prevents re-introduction). Contact dimension (75/100)
is the remaining weakness — three open patterns:
sister-club cross-contamination, town-portal-as-website, local-news domain
variants. See VERIFICATION.md "Time series" section.

## Sljedeće faze (otvorene ideje)

- **Sister-club detector** — flag clubs whose `website` domain canonical name
  doesn't match own canonical_name (catches "Dinamo Odra got Segesta Sisak's
  data" leak class)
- **Geocoder precision pass** — Croatia-G coords 19 km off, Dinamo-O 22 km
  off; replace village-centroid with stadium-pin lookups on HNS Semafor pages
- Email/phone deliverability audit (MX lookup, regex sanity)
- Recurring snapshot job — re-run ingest monthly za nove sezone
- Self-hosted Firecrawl stack za eliminaciju Cloud troška za buduće re-runove
- SMS provider integracija (Vox/Infobip CSV import format)
