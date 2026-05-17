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

CLUB: HNK Vukovar 1991 (slug=vukovar-1991-osijek, tier=1)
  city: Osijek
  address: Rudolfa Perešina 8, 32 000 Vukovar
  email: info@hnk-vukovar1991.hr
  website: https://hnk-vukovar1991.hr/
  stadium_name: Stadion Gradski vrt
  stadium_capacity: 18856
  founded_year: 2012
  lat: 45.545271
  lng: 18.695282
  leagues: T1: SuperSport HNL (25/26); T3: 3. HNL Istok (2021/22)

CLUB: RNK Split (slug=split, tier=3)
  city: Split
  address: Hrvatske mornarice 10, 21000 Split
  email: radnickinogometniklub.split.1912@gmail.com
  website: https://rnksplit1912.hr
  fb_url: https://www.facebook.com/p/RNK-Split-1912-61561985783930/
  ig_url: https://www.instagram.com/rnksplit.1912/
  president: Damir Tomić
  stadium_name: Stadion Park mladeži
  stadium_capacity: 4000
  founded_year: 1912
  lat: 43.519154
  lng: 16.444175
  leagues: T3: 3. HNL Jug (2021/22); T6: 1. ŽNL (SDŽ) (hrnogomet-season-1007)

CLUB: NK Psunj Sokol (slug=psunj-sokol, tier=5)
  city: Okučani
  county: Brodsko-posavska županija
  phone: 00385 35 371 001
  phone_kind: landline
  phone_e164: +38535371001
  email: opcina.okucani@opcokucani.tcloud.hr
  founded_year: 1947
  lat: 45.2602183
  lng: 17.1997528
  leagues: T5: MŽNL SB-PŽ (hrnogomet-season-917)

CLUB: NK Tomislav (Đ) (slug=tomislav-d, tier=6)
  city: Berek
  county: Bjelovarsko-bilogorska županija
  address: Berek-43232BEREK-Hrvatska
  fb_url: https://www.facebook.com/p/Nk-Tomislav-Berek-100054533046526/
  founded_year: 1998
  lat: 45.9800051
  lng: 16.9041385
  leagues: T6: Elitna ŽNL (KKŽ) (hrnogomet-season-929); T7: 2. ŽNL (BBŽ) (hrnogomet-season-920)

CLUB: NK Adriatic (slug=adriatic, tier=7)
  county: Splitsko-dalmatinska županija
  website: https://www.nkadriatic.hr/
  founded_year: 2010
  lat: 43.5589389
  lng: 16.3606824
  leagues: T7: 2. ŽNL (SDŽ) (hrnogomet-season-1011)
