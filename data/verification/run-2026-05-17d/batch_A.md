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
  address: Maksimirska 128, 10000 Zagreb
  phone: +38512386111
  phone_kind: landline
  phone_e164: +38512386111
  website: https://gnkdinamo.hr/hr
  stadium_name: Stadion Maksimir
  stadium_capacity: 24851
  founded_year: 1911
  lat: 45.818604866515
  lng: 16.01835977764
  leagues: T1: SuperSport HNL (25/26)

CLUB: HNK Zadar (slug=zadar, tier=3)
  city: Zadar
  website: https://hnkzadar.hr/
  fb_url: https://facebook.com/hnkzadarnogomet
  ig_url: https://instagram.com/hnk.zadar
  x_url: https://x.com/hnkzadar
  stadium_name: Stadion Stanovi
  stadium_capacity: 5860
  founded_year: 1949
  lat: 44.11972
  lng: 15.24222
  leagues: T3: 3. HNL Jug (2021/22); T4: 3. NL - Jug (25/26)

CLUB: NK Kurilovec Velika Gorica (slug=kurilovec-velika-gorica, tier=4)
  city: Velika Gorica
  website: https://nk-kurilovec.hr
  stadium_name: Sportsko-rekreacijski centar Udarnik
  founded_year: 2018
  lat: 45.7022546
  lng: 16.0717133
  leagues: T3: 3. HNL Centar (2021/22); T4: 3. NL - Centar (25/26)

CLUB: NK Dubravčan (DD) (slug=dubravcan-dd, tier=6)
  city: Donja Dubrava
  county: Međimurska županija
  address: Krbulja 21, 40 328 Donja Dubrava
  phone: 098/9323-599
  phone_kind: mobile
  phone_e164: +385989323599
  email: nkdubravcan@gmail.com
  x_url: https://twitter.com/home?status=https%3a%2f%2fsemafor.hns.family%2fklubovi%2f369%2fnk-dubravcan-dd%2f
  president: FRANJO KNEZ
  stadium_name: Krbulja
  founded_year: 1927
  lat: 46.3154534
  lng: 16.8053197
  leagues: T6: Premier liga (Međimurska) (hrnogomet-season-947)

CLUB: NK Poljana (slug=poljana, tier=7)
  city: Poljana
  county: Sisačko-moslavačka županija
  address: Kolodvorska 20 C, Poljana, 34543 Poljana
  phone: +385 34 431 351
  phone_kind: landline
  phone_e164: +38534431351
  email: danijel.vincetic@hep.hr
  president: Nevrkla Darko
  lat: 45.446002
  lng: 16.2826488
  leagues: T7: 2. ŽNL - NS Kutina (SMŽ) (hrnogomet-season-907)
