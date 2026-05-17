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

CLUB: HNK Rijeka (slug=rijeka, tier=1)
  city: Rijeka
  address: Rujevica 10, 51000 Rijeka
  phone: +385 51 563 623
  phone_kind: landline
  phone_e164: +38551563623
  email: info@nk-rijeka.hr
  website: https://nk-rijeka.hr/
  fb_url: https://www.facebook.com/nk.rijeka
  ig_url: https://instagram.com/nk_rijeka
  x_url: https://twitter.com/nkrijeka
  stadium_name: Stadion HNK Rijeka Dean Šćulac
  stadium_capacity: 8279
  founded_year: 1946
  lat: 45.347681
  lng: 14.402144
  leagues: T1: SuperSport HNL (25/26)

CLUB: HNK Primorac Biograd na Moru (slug=primorac-biograd-na-moru, tier=4)
  city: Biograd na Moru
  address: Ruđera Boškovića 9, 23210 Biograd na Moru
  fb_url: https://www.facebook.com/100hnkprimoracbnm/?locale=hr_HR
  x_url: https://twitter.com/home?status=https%3a%2f%2fsemafor.hns.family%2fklubovi%2f207%2fhnk-primorac-bnm%2f
  stadium_name: Kažimira i Silvija
  founded_year: 1919
  lat: 43.9403659
  lng: 15.4551594
  leagues: T3: 3. HNL Jug (2021/22); T4: 3. NL - Jug (25/26)

CLUB: NK Garić (G) (slug=garic-g, tier=5)
  city: Garešnica
  address: Petra Svačića 11f,43280 Garešnica
  phone: 043531006
  phone_kind: landline
  phone_e164: +38543531006
  website: https://www.znsvpz.hr/klub/garic/32/
  president: Ivan Ribarić
  lat: 45.5739183
  lng: 16.9407213
  leagues: T5: 4.NL BJ-KC-VT (hrnogomet-season-512)

CLUB: NK Trnski (slug=trnski, tier=6)
  city: Nova Rača
  county: Bjelovarsko-bilogorska županija
  address: Trg S. Radića 56, 43272 Nova Rača
  phone: (043) 886 036
  phone_kind: landline
  phone_e164: +38543886036
  email: financije@nova-raca.hr
  website: https://nova-raca.hr/
  lat: 45.7856351
  lng: 16.7698507
  leagues: T6: 1. ŽNL (BBŽ) (hrnogomet-season-919)

CLUB: NK Dubrava (Z) (slug=dubrava-z, tier=8)
  county: Brodsko-posavska županija
  lat: 45.1689901
  lng: 18.1554033
  leagues: T8: 3. ŽNL Istok (BPŽ) (hrnogomet-season-934)
