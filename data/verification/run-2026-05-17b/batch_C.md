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

CLUB: NK Crikvenica (slug=crikvenica, tier=4)
  city: Crikvenica
  fb_url: https://www.facebook.com/nkcrikvenica.hr/
  stadium_name: Gradski stadion Crikvenica
  stadium_capacity: 2050
  lat: 45.1737049
  lng: 14.6927906
  leagues: T4: 3. NL - Zapad (25/26)

CLUB: NK Top (slug=top, tier=5)
  city: KERESTINEC
  county: Zagrebačka županija
  address: Rimski trg 1, 10431, KERESTINEC, Hrvatska
  phone: 3370679
  phone_kind: unknown
  email: nogometni.klub.top.kerestinec@zg.t-com.hr
  president: MARIJAN JORDAN
  lat: 45.7761185
  lng: 15.800822
  leagues: T5: 4. NL Središte Zagreb - B (hrnogomet-season-895)

CLUB: NK BSK Budaševo (slug=bsk-budasevo, tier=6)
  city: Budaševo
  county: Sisačko-moslavačka županija
  address: Trg Marijana Šokčevića 1, Budaševo
  email: nkbsk1932budasevo@gmail.com
  lat: 45.47606
  lng: 16.4368967
  leagues: T6: 1. ŽNL (SMŽ) (hrnogomet-season-963)

CLUB: NK Gaj Brođanci (slug=gaj-brodanci, tier=8)
  county: Osječko-baranjska županija
  fb_url: https://www.facebook.com/nkgajbrodanci/?locale=hr_HR
  lat: 45.5435202
  lng: 18.4498129
  leagues: T8: 3. ŽNL Valpovo (OBŽ) (hrnogomet-season-911)
