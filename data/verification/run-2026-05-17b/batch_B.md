You are auditing the data quality of a Croatian football clubs database. Use WebSearch + WebFetch to verify each field per the rubric below.

== METHODOLOGY ==

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

`overall` = mean of non-null dimension scores.

== CLUBS TO VERIFY ==

CLUB: GNK Dinamo Zagreb (slug=dinamo-zagreb, tier=1)
  city: Zagreb
  website: https://gnkdinamo.hr/hr
  stadium_name: Stadion Maksimir
  stadium_capacity: 24851
  founded_year: 1911
  lat: 45.818604866515
  lng: 16.01835977764
  leagues: T1: SuperSport HNL (25/26)

CLUB: NK Kustošija (slug=kustosija-zagreb, tier=3)
  city: Zagreb
  address: Sokolska 47a, Zagreb
  phone: +385 95 8785 292
  phone_kind: mobile
  phone_e164: +385958785292
  email: info@nk-kustosija.hr
  website: https://nk-kustosija.hr
  stadium_name: Stadion Kustosija
  stadium_capacity: 2500
  lat: 45.81444
  lng: 15.97798
  leagues: T3: 2. NL (25/26)

CLUB: Rugvica Sava 1976 (slug=rugvica-sava-1976, tier=5)
  city: Rugvica
  phone: 01 2753 419, 01 2753 012
  phone_kind: unknown
  email: urednistvo@dugoselska-kronika.hr
  website: https://www.dugoselski-sport.hr/index.php
  fb_url: https://www.facebook.com/dugoselskakronika/
  ig_url: https://www.instagram.com/dugoselskakronika/?utm_source=ig_web_button_share_sheet&igshid=OGQ5ZDc2ODk2ZA==
  president: Ivica Zelenbrz
  founded_year: 1976
  lat: 45.7439468
  lng: 16.232906
  leagues: T5: 4. NL Središte Zagreb - B (hrnogomet-season-895)

CLUB: NK Sloga (Š) (slug=sloga-s, tier=6)
  county: Međimurska županija
  fb_url: https://www.facebook.com/nkslogack/?locale=hr_HR
  president: Tihomir Blažeka
  lat: 46.3775096
  lng: 16.4507241
  leagues: T6: Premier liga (Međimurska) (hrnogomet-season-947)

CLUB: NK Dinamo (O) (slug=dinamo-o, tier=7)
  city: Sisak
  county: Sisačko-moslavačka županija
  address: Antuna Cuvaja 16/II kat, 44000 Sisak
  phone: +385 44 540 088
  phone_kind: landline
  phone_e164: +38544540088
  email: hnk.segesta.sisak@sk.t-com.hr
  website: https://hnk-segesta.hr/
  lat: 45.5713115
  lng: 16.6270566
  leagues: T7: 2. ŽNL - NS Kutina (SMŽ) (hrnogomet-season-907)
