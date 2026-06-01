# Što još nedostaje u katalogu

> Stanje: 2026-06-02 · baza: **921** klubova · vidi [issue #1](https://github.com/domovinatv/klubovi.domovina.ai/issues/1)

## Kontekst — `901` nikad nije bio "svi klubovi u HR"

Početnih 901 klubova izgrađeno je iz **muških** županijskih liga (hrnogomet.hr).
HNS Semafor crawl (`scripts/17c_crawl_semafor_full.py`) korišten je samo za
**enrichment** tih 901 — svaki klub koji je crawl otkrio, a nije se matchao na
postojeći, **odbačen je**. Cijela ženska liga, futsal, dio muških i mladež pali
su kroz tu rupu. Prijava (M. Tolić, trener ŽNK Donat) otkrila je simptom.

## Kvantifikacija iz vlastitog cachea (`data/raw/semafor/`, 1078 stranica)

| | broj |
|---|---|
| Semafor stranica skinuto | 1078 |
| povezano na klub u bazi | 440 |
| nepovezano | 884 |
| └ ime se već poklapa (duplikat/ambiguous, isti razred) | 575 |
| └ **genuino novi klub** | **309** |

Razred = Ž (ženski) / F (futsal) / M (muški). Dedup **mora** čuvati razred —
ŽNK Rijeka i HNK Rijeka su različiti klubovi, ne duplikat.

## ✅ Riješeno — 20 ŽNK ingestirano

`scripts/33_ingest_znk.py --write` → +20 ženskih klubova (ŽNK Virovitica već je
bio u bazi). Donat = id 902. Vidi `data/exports/znk_and_missing_candidates.xlsx`.

## ⬜ Preostalo — ~289 genuino novih klubova

Izvor i parsiranje već postoje (cache + `src/semafor.py`); fali samo INSERT put
(po uzoru na `scripts/33_ingest_znk.py`) + provjera flagova. Pregled u
`data/exports/znk_and_missing_candidates.xlsx` (stupac `preporuka`):

| preporuka | broj | što |
|---|---|---|
| 🟢 DODAJ | ~283 | čisti muški/veterani zapisi sa Semafora |
| 🟡 PROVJERI | 5 | **II/B rezervne momčadi** — prvi tim vjerojatno već u bazi, ne duplicirati: GNK Dinamo II, NK Osijek II, NK Bedekovčina II, NK Lobor II, NK Mladost Satnica Đakovačka 2 |

### Na što paziti pri sljedećem ingestu
1. **Dedup po razredu**, ne po golom imenu — inače ženski/futsal nestaju (ista greška kao prije).
2. **II/B momčadi preskočiti** ili vezati na prvi tim, ne kao zasebne klubove.
3. **City→county** treba proširiti mapu (`CITY_COUNTY` u 33) — ~289 klubova pokriva puno više od 15 gradova; razmisli o lookupu iz postojećih DB redova ili Nominatim reverse.
4. **Stub zapisi** (bez osnutka/adrese/koord) — npr. ŽNK Dilj (V) je ingestiran ali je tanak; provjeri postoji li klub uopće prije masovnog uvoza.

## ⬜ Šira rupa — cache nije puni svemir

BFS je dosegao samo klubove **linkane iz natjecanja koja je obišao**. Pravi
ukupan broj registriranih HR klubova je veći. Da se zaključa:

- **Brute-force ID probe** Semafor `/klubovi/1..200000/` — ~10k zahtjeva, ~70 min
  uz 0.4s throttle (vidi `next_session_semafor.md`). Surfat će klubove koje
  nijedna trenutna liga ne hostira (ugašeni, novoregistrirani, ženske niže lige).
- **346 ambiguous** istoimenih (npr. 4× NK Sloga Zagreb) i dalje neriješeno —
  treba disambiguator (Semafor `short_name` zagrade, godina osnutka).

## Datoteke
- `scripts/33_ingest_znk.py` — ŽNK ingest (gotov, idempotentan)
- `data/exports/znk_and_missing_candidates.xlsx` — 309 kandidata, obojano po preporuci
- `data/exports/znk_and_missing_candidates.csv` — isti podaci, CSV
- `data/raw/semafor/<id>.html` — cache svih stranica, ne treba ponovni crawl
