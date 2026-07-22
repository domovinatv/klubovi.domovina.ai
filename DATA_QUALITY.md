# Data quality — poznati sustavni bugovi

Stanje: 2026-07-22. Baza: `data/clubs.db`, 1014 klubova.

Ovaj dokument bilježi **uzroke** grešaka u katalogu, ne pojedinačne greške.
Detekcija + guard su implementirani i commitani (vidi "Status popravka" na dnu).
**Popravak podataka (`61 --execute`) još nije pokrenut** — pokreće se ručno tek
nakon verifikacije `collisions.csv`.

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

## Status popravka (2026-07-22)

Implementirano i commitano (5 commita, `2c5abd8`..`6015d95`). Kod di'ram gore.
`data/clubs.db` **nije diran** — dry-run + testovi rade nad sintetičkom bazom.

| korak | datoteka | stanje |
|---|---|---|
| detekcija | `scripts/60_detect_collisions.py` + `src/collisions.py` | ✅ read-only, CSV svjež |
| popravak | `scripts/61_quarantine_leaks.py` | ✅ dry-run testiran, `--execute` **čeka ručno pokretanje** |
| guard | `src/backfill.py` + `src/hrnogomet.py` | ✅ 2 provjere, 69 testova |
| geo reverify | `scripts/62_reverify_geo.py` | ✅ read-only |
| testovi | `tests/` | ✅ 69 passed, bez mreže, sintetička baza |

### Rezultat detekcije (`collisions_summary.json`)

| polje | grupe | owner | orphan | ambiguous | klubova ↓ |
|---|---:|---:|---:|---:|---:|
| phone | 86 | 47 | 69 | 107 | 69 |
| email | 85 | 45 | 67 | 111 | 67 |
| oib | 73 | 38 | 58 | 83 | 58 |
| address | 83 | 43 | 66 | 105 | 66 |
| website | 56 | 30 | 48 | 133 | 48 |
| fb_url | 42 | 19 | 30 | 112 | 30 |
| latlng | 73 | 33 | 56 | 97 | 56 |

154 klubova ima ≥1 orphan verdikt; popravak dira 133. Geo je **detect-only**
(dvije lokacije na istom pinu je često legitimno dijeljen teren).

### Naredba za popravak

```bash
uv run python scripts/60_detect_collisions.py           # već pokrenuto
uv run python scripts/61_quarantine_leaks.py            # dry-run, provjeri
uv run python scripts/61_quarantine_leaks.py --execute  # popravak (backup + data_repairs)
```

### Tri nalaza koja su promijenila plan

1. **`countyId` NE rješava 31 klub — rješava 0/31.** Zahtjev 4 iz originalnog
   plana ("popuni county preko hrnogomet mape") ne radi: tim klubovima je
   `countyId` 24/37/-8, što su *lige* ("4./3. Nogometna Liga") pa `priority==50`
   filter ispravno odbija. Ostaje im samo `registry_naziv` (30/31, ali 19 je
   krivih N:1 matcheva koje 61 briše) i Semafor (15/31). → 20 klubova ostaje bez
   provjerljivog geo signala; guard ih tada odbija (sigurno, ali backfill ih ne
   može popuniti bez ručnog rada).

2. **County sam po sebi ne može biti guard.** Zabok je u Krapinsko-zagorskoj —
   riječi nemaju zajednički korijen, pa je prvi pokušaj odbijao *ispravne*
   ekstrakcije. Rješenje: **poštanski broj** (prva 2 znaka → županija; 43000 =
   Bjelovarsko-bilogorska, 49210 = Krapinsko-zagorska). To je jedini signal koji
   razdvaja Ždralovi od Zaboka kad županija nije nazvana po sjedištu.

3. **Redoslijed je load-bearing.** Guard se oslanja na `registry_naziv` kao
   specifičan signal, a 19 tih zapisa je krivo. Zato **61 mora ići prije
   re-backfilla** — inače guard verificira protiv istog krivog podatka.

### Ograničenja koja vrijede za cijeli popravak

- Detekcija i popravak su **100% deterministički Python** — nula LLM poziva.
- Jedini dopušteni vanjski poziv je **Firecrawl**, i to samo iza `--execute`.
- Skripte su idempotentne; drugi `--execute` je no-op (plan se gradi iz živih
  vrijednosti, već-NULL polja se preskaču).
- Testovi idu nad sintetičkom SQLite bazom u `tmp_path`, nikad nad
  `data/clubs.db`, i ne rade mrežni poziv. Ždralovi-grupa od 6 klubova i
  Graničar-OIB grupa od 8 su obavezni fixturi.

### Nove tablice (kreira ih `61 --execute`)

- `data_repairs (id, club_id, field, old_value, new_value, reason, ran_at)` —
  audit svake poništene vrijednosti, potpuno rekonstruktivno.
- `backfill_queue (club_id, fields JSON, reason, queued_at, done_at)` —
  očišćeni klubovi koje kasniji backfill pokupi.
