# Data quality — poznati sustavni bugovi

Stanje: 2026-07-21. Baza: `data/clubs.db`, 1014 klubova.

Ovaj dokument bilježi **uzroke** grešaka u katalogu, ne pojedinačne greške.
Popravak još nije napravljen — vidi "Plan popravka" na dnu.

---

## 1. Namesake leak u backfillu (glavni uzrok)

### Simptom

`https://klubovi.domovina.ai/klub/mladost-z` — NK Mladost iz **Zaboka** —
prikazan je s gradom Bjelovar, adresom u Ždralovima, te telefonom, mailom,
webom i Facebookom kluba NK Mladost Ždralovi.

### Lanac

| korak | što se dogodilo |
|---|---|
| izvor `data/raw/hrnogomet/teams/1035.json` | `teamName: "NK Mladost (Z)"`, **bez grada**, samo `countyId: 24` |
| `src/backfill.py` | Firecrawl search `"NK Mladost (Z) nogometni klub kontakt"` |
| rezultati (`backfill_runs` run_id 471) | 1. `mladost-zdralovi.hr` ← scrapean<br>2. `nk-mladost-zabok.hr` ← **ispravan, ignoriran**<br>3. `semafor.hns.family/en/clubs/1083/…` |
| upis | `city, address, website, email, phone, fb_url, ig_url, founded_year` — svi iz Ždralova |
| `scripts/27_google_geocode.py` | query `"NK Mladost (Z), Bjelovar, Hrvatska"` → nađe NK Mladost Ždralovi → `geo_source='both'` |

Korijen: HNS/hrnogomet feed disambiguira istoimene klubove **slovom u zagradi**
(`(Z)`, `(LB)`, `(NV)`) i **ne daje grad**. Backfill uzima prvi search rezultat.
Za 263 kluba s paren-imenom to je lutrija.

### Zašto guard nije upalio

`src/backfill.py:294`:

```python
if _PAREN_RE.search(name) and club_row.get("county"):
```

Dvije rupe:

1. `and club_row.get("county")` — klub 888 ima `county = ''`, guard se preskoči
   u cijelosti. **31 klub** ima paren-ime i prazan county.
2. Provjera je preslaba i kad se izvrši: traži samo da izvučena adresa ne
   sadrži jedan od hardkodiranih gradova (`split, zagreb, rijeka, osijek,
   velika gorica`). `Ždralovi, Bjelovar` prolazi bez problema.

---

## 2. N:1 match na Registar udruga

`scripts/21_match_udruga.py` mapirao je više paren-namesake klubova na **isti**
zapis Registra udruga, pa dijele OIB, predsjednika i registry adresu.

| OIB | broj klubova | slugovi |
|---|---|---|
| `30169335717` | 8 | granicar-tucenik, granicar-l, granicar-nv, granicar-sk, granicar-brodski-varos, granicar-mm, granicar-klakar, granicar-ss |
| `16256194567` | 4 | radnicki, radnicki-m, radnicki-v, radnicki-z |
| `38668684058` | 4 | omladinac-v, omladinac-j, omladinac-p, omladinac-s |
| `65720969977` | 2 | mladost-pavlovci (ispravno), mladost-z (krivo) |

Matcher iz `workflow_hr_name_matching` postiže 97% *recall*, ali nema
**uniqueness constraint** — ne provjerava je li registry zapis već potrošen.

---

## 3. Geo verifikacija je potvrdila zatrovan ulaz

**`geo_source='both'` NIJE dokaz ispravnosti.**

`scripts/27_google_geocode.py:239` gradi query iz `{canonical_name}, {city},
Hrvatska`. Ako je `city` došao iz backfilla (dakle možda krivi grad), Google i
Nominatim se slože oko **krivog** mjesta i zapis dobije `geo_source='both'`,
`geo_truth_source='osm:tie'`.

4-slojna verifikacija iz `workflow_geo_verification` je bila interno
konzistentna — samo je krenula od zatrovanog ulaza. Svaka buduća geo provjera
mora presjeći s `backfill_runs.fields_filled LIKE '%city%'`.

---

## 4. Blast radius

Broj grupa u kojima ≥2 kluba dijele istu vrijednost:

| polje | kolizijskih grupa |
|---|---|
| email | 86 |
| phone | 81 |
| oib | 73 |
| lat/lng (identičan par) | 73 |
| website | 46 |
| fb_url | 41 |

Najveći primjer po kontaktu — 6 klubova na istom telefonu `+385 91 5210 944`,
mailu `info@nk-mladost.hr` i webu `mladost-zdralovi.hr`:

| slug | city | vjerojatni vlasnik |
|---|---|---|
| mladost-zdralovi | Ždralovi | **da** — domena sadrži `zdralovi` |
| mladost-o | Bjelovar | ne |
| mladost-np | Bjelovar | ne |
| mladost-sm | Bjelovar | ne |
| mladost-f | Bjelovar | ne |
| mladost-z | Bjelovar | ne — stvarno Zabok |

Utjecaj na glavni use-case: `phone_e164 + has_mobile` filter za SMS outreach
isporučuje 5 klubova na broj koji pripada šestom. Duplicirani broj = duplicirana
poruka istom primatelju.

---

## Plan popravka

Redoslijed je bitan — popravi kod, pa tek onda podatke.

1. **`scripts/60_detect_collisions.py`** (read-only) — nađi sve kolizijske grupe
   po normaliziranoj vrijednosti (telefon → E.164, web → registrable domain,
   mail lowercase, koordinate na 5 decimala). Za svaku grupu odredi
   owner-kandidata **determinističkim** signalima: token iz `canonical_name`/
   `city` u domeni/mailu/FB slugu, poklapanje `registry_naziv`, neparen-ime,
   neovisna potvrda preko `semafor_url`/`sofascore_url`.
   Izlaz: `data/exports/collisions.csv` s verdiktom `owner|orphan|ambiguous`.

2. **`scripts/61_quarantine_leaks.py`** (dry-run default, `--execute` za pisanje)
   — za `orphan` **poništi** zaražena polja. Nikad ne pogađaj ispravnu
   vrijednost, samo briši krivu. Loguj u novu tablicu `data_repairs`
   (`club_id, field, old_value, new_value, reason, ran_at`) da se sve može
   rekonstruirati. Poništene klubove gurni u backfill queue.

3. **Fix `src/backfill.py`** — makni `and club_row.get("county")`; zamijeni
   hardkodiranu blacklist gradova provjerom protiv poznatog geo signala
   (`countyId` iz hrnogomet feeda, mjesto iz `semafor_url`, mjesto iz
   `registry_naziv`); kad više search rezultata izgleda kao različiti klubovi
   istog imena → `status="ambiguous"`, ne piši ništa. Popuni `county` za 31
   klub preko postojeće mape u `scripts/03_enrich_counties.py`.

4. **`scripts/62_reverify_geo.py`** (read-only) — izvezi u
   `data/exports/geo_suspect.csv` sve klubove gdje je `city` upisan backfillom
   **i** `geo_source='both'`. To su lažno potvrđeni zapisi.

5. **Tek nakon verifikacije** pokreni backfill za očišćene klubove.

### Ograničenja koja vrijede za cijeli popravak

- Detekcija i popravak su **100% deterministički Python** — nula LLM poziva.
  Backfill preko LLM subagenata je preskup za 1000 klubova.
- Jedini dopušteni vanjski poziv je **Firecrawl**, i to samo iza `--execute`.
- Skripte moraju biti idempotentne i pokretljive u pozadini (progress log).
- Testovi idu nad sintetičkom in-memory SQLite bazom, nikad nad `data/clubs.db`,
  i ne smiju raditi mrežni poziv. Ždralovi-grupa od 6 klubova je obavezan
  fixture.
