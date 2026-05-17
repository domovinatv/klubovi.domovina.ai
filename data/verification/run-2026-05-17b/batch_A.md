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

CLUB: HNK Gorica (slug=gorica-velika-gorica, tier=1)
  city: Velika Gorica
  address: Hrvatske Bratske Zajednice 80, HR-10410 Velika Gorica
  phone: +385 1 6265 152
  phone_kind: landline
  phone_e164: +38516265152
  email: info@hnk-gorica.hr
  website: https://hnk-gorica.hr
  stadium_name: Gradski stadion Velika Gorica
  stadium_capacity: 5200
  founded_year: 2009
  lat: 45.72399
  lng: 16.073116
  leagues: T1: SuperSport HNL (25/26)

CLUB: NK Lučko (slug=lucko-zagreb, tier=3)
  city: Zagreb
  address: Puškarićeva ulica 122, 10250 Lučko
  phone: 01/6530-696
  phone_kind: landline
  phone_e164: +38516530696
  email: info@nk-lucko.hr
  website: https://nk-lucko.hr/
  stadium_name: Stadion Lučko
  stadium_capacity: 1500
  founded_year: 1930
  lat: 45.76049
  lng: 15.867824
  leagues: T3: 3. HNL Centar (2021/22); T3: 2. NL (25/26)

CLUB: NK Bilogora 91 (slug=bilogora-91, tier=4)
  city: Grubišno Polje
  address: Trg bana Josipa Jelačića br. 1, Grubišno Polje
  website: https://grubisnopolje.hr/
  founded_year: 2011
  lat: 45.705039
  lng: 17.1741882
  leagues: T4: 3. NL - Sjever (25/26); T5: 4.NL BJ-KC-VT (hrnogomet-season-512)

CLUB: NK Croatia (G) (slug=croatia-g, tier=6)
  city: Grabrovnica
  county: Virovitičko-podravska županija
  address: Grabrovnica bb, 33405, Grabrovnica
  phone: 033 714 599
  phone_kind: landline
  phone_e164: +38533714599
  lat: 45.8349096
  lng: 17.3845292
  leagues: T6: 1. ŽNL (VPŽ) (hrnogomet-season-965)

CLUB: NK BSK Brdovec (slug=bsk-brdovec, tier=7)
  city: Brdovec
  county: Zagrebačka županija
  address: Ulica Pavla Beluhana 2, 10291, Brdovec, Hrvatska
  phone: 0915281678
  phone_kind: mobile
  phone_e164: +385915281678
  email: rnovosel3@gmail.com
  president: Robert Novosel
  lat: 45.8685003
  lng: 15.7491259
  leagues: T7: 2. ŽNL - Zapad (Zagrebačka) (hrnogomet-season-898)
