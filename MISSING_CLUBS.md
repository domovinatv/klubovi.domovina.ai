# Što još nedostaje u katalogu

> Stanje: 2026-06-02 · baza: **1014** klubova (901 → +20 ŽNK → +93 gated) · vidi [issue #1](https://github.com/domovinatv/klubovi.domovina.ai/issues/1)

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

## ✅ Riješeno — 20 ŽNK + 93 gated muška kluba (DB 901 → 1014)

**Faza 1 — `scripts/33_ingest_znk.py --write`**: +20 ženskih klubova (ŽNK
Virovitica već u bazi). Donat = id 902. Logoi sa Semafora
(`scripts/34_fetch_semafor_logos.py`). Geo: 10 both / 6 nominatim / 3 google /
1 semafor, svih 20 verificirano i na karti.

**Faza 2 — `scripts/35_ingest_missing_gated.py`** (strogi quality gate, izbor
korisnika): od 271 stagiranih kandidata, kroz puni geo pipeline (Nominatim →
Google → pick_truth), **zadržano samo 93** koji dosegnu `geo_source='both'` (oba
geokodera se slažu) unutar HR bbox-a. Svih 93 ima grad + županiju + dvostruko
potvrđene koordinate. **167 odbijeno** → `data/exports/missing_clubs_gate_rejects.csv`
(nisu smeće, samo nedovoljno potvrđeni). **11 dodatnih obrisano** kao
proximity-duplikati postojećih klubova (npr. "NK Radnički (D)" = "NK Radnički
Dalj", 0 m) — semafor_url prebačen na postojeći prije brisanja.

## ⬜ Pending pipeline — 179 klubova za cherry-pick

Klubovi koji nisu prošli strogi `both` gate **nisu obrisani iz pipelinea** —
ostaju kao "pending" red. Kad se netko javi da nedostaje klub, lako ga
cherry-pickamo. Lista je **regenerabilna** (deterministička iz cachea + trenutne
baze), pa preživljava brisanje stagiranih redaka:

```
uv run python scripts/35_ingest_missing_gated.py --pending
# → data/exports/missing_clubs_pending.csv  (semafor_id, naziv, grad, adresa, moguci_duplikat, semafor_url)
```

Trenutno **179** (167 gate-rejects + 11 proximity-dupe + 1), od toga **14
označeno `moguci_duplikat=DA`** (vjerojatno već u bazi pod varijantom imena —
ne cherry-pickati naslijepo). Razlozi zašto su pali: ~130 Google-override
(npr. suvenirnica Hajduk), ~35 nominatim-only, 2 semafor.

### Cherry-pick workflow (kad se javi da fali klub X)
1. Nađi X u `missing_clubs_pending.csv` po imenu → uzmi `semafor_id`.
2. Provjeri `moguci_duplikat` — ako DA, prvo provjeri postoji li već u bazi.
3. Re-stage taj jedan ID + geocode (Nominatim/Google) + verify lokaciju.
4. Dodaj ako je lokacija potvrđena; logo preko `scripts/34_fetch_semafor_logos.py`.

*(`data/exports/` je gitignoran — zato je generator skripta to što se commita,
a CSV se regenerira komandom gore.)*

### Posebno preskočeno (nije u pending listi)
| | broj | što |
|---|---|---|
| II/B rezervne momčadi | 5 | GNK Dinamo II, NK Osijek II, NK Bedekovčina II, NK Lobor II, NK Mladost Satnica Đakovačka 2 — prvi tim već u bazi |
| stubovi bez adrese | 2 | NK Lobor I, NK Bedekovčina I |

### Naučene lekcije (za sljedeći ingest)
1. **Dedup po razredu** (Ž/F/M), ne po golom imenu — inače ženski nestaju.
2. **Proximity-dedup OBAVEZAN**: class+core dedup promašuje "(KS)" vs "Kaštel
   Sućurac" varijante; provjeri ima li novi klub postojeći unutar ~120 m.
3. **Google override-filteri su za muške klubove** — kod ŽNK lažno prolaze
   (suvenirnica "Prodavaonica obilježja HNK Hajduk" umalo postala teren).
4. **city_from_address ne hvata sve formate** (razmaknuti zip "40 313", bez
   zareza) — 8/104 imalo adresu u `city` polju; popravljeno parsiranjem repa.
5. **Županija iz poštanskog broja** (2-znamenkasti prefiks → županija) kad
   grad nije u postojećoj DB mapi.

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
