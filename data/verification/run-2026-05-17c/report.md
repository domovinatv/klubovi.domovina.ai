# Pipeline verification report — 2026-05-17

Sample size: **15** clubs (stratified by tier)
**Overall pipeline reliability: 89.1 / 100**

## Dimension scores

| Dimension | Score | Stars |
|---|---:|---|
| identity | 96.7 | ★★★★★★★★★★ |
| location | 93.3 | ★★★★★★★★★ |
| contact | 66.7 | ★★★★★★★ |
| phone_kind | 94.4 | ★★★★★★★★★ |
| coordinates | 90.0 | ★★★★★★★★★ |
| league | 96.7 | ★★★★★★★★★★ |

## Per-club details

| slug | tier | overall | issues |
|---|---:|---:|---|
| gorica-velika-gorica | T1 | 1.00 | none; address, phone, email, website all match official club site |
| lucko-zagreb | T3 | 1.00 | none; all contact fields verified against official nk-lucko.hr |
| croatia-g | T6 | 1.00 | none; phone 033 prefix is correct Virovitica-area landline; club confirmed in 1. ŽNL VPŽ |
| dinamo-zagreb | T1 | 1.00 | none; all fields verified against official gnkdinamo.hr |
| kustosija-zagreb | T3 | 1.00 | minor: site lists email as info@kustosija.hr while DB has info@nk-kustosija.hr (same domain family, likely both valid) |
| vukovar-1991-osijek | T1 | 1.00 | website returned 403 to scraper but domain matches club; FB/IG not provided |
| top | T5 | 1.00 | phone 3370679 is malformed (7 digits, no area code) so unknown classification is correct; t-com.hr email is plausible legacy account |
| bsk-budasevo | T6 | 1.00 | — |
| gaj-brodanci | T8 | 1.00 | — |
| bsk-brdovec | T7 | 0.92 | email rnovosel3@gmail.com is president's personal gmail (belongs to club officer, but not an institutional address); 091 prefix correctly classified as mobile; league confirmed via Semafor (2. NSZŽ Zapad) |
| crikvenica | T4 | 0.90 | FB page could not be definitively verified as official (page content truncated by scraper); URL slug matches club name plausibly |
| bilogora-91 | T4 | 0.80 | website https://grubisnopolje.hr/ is the municipality portal, not the club (clear leak); stadium_name should be 'Bilogorac' not 'NK Bilogora 91'; club's actual web presence is facebook.com/nkbilogora |
| rugvica-sava-1976 | T5 | 0.75 | contact leak: email urednistvo@dugoselska-kronika.hr, website dugoselski-sport.hr, fb/ig dugoselskakronika all belong to local newspaper Dugoselska Kronika, not the club; phone_kind 'unknown' but 01-prefix is clearly landline (Zagreb area) |
| sloga-s | T6 | 0.50 | club is NK Sloga Štrigova (city Štrigova) but fb_url nkslogack belongs to NK Sloga Čakovec (different club); president Tihomir Blažeka is associated with Sloga Čakovec nogometna škola; coords 46.3775,16.4507 are near Čakovec, Štrigova is at ~46.51,16.36 (>10km off); county Međimurska correct |
| dinamo-o | T7 | 0.50 | major data leak: address Antuna Cuvaja 16 is NSSMŽ (county FA) HQ; phone +38544540088, email hnk.segesta.sisak@sk.t-com.hr, website hnk-segesta.hr all belong to HNK Segesta Sisak (tier 2 club), not this tier 7 club; NK Dinamo Kutina exists but hasn't competed since 2020/21; coords near Popovača, ambiguous between Sisak/Kutina |
