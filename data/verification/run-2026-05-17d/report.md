# Pipeline verification report — 2026-05-17

Sample size: **15** clubs (stratified by tier)
**Overall pipeline reliability: 89.1 / 100**

## Dimension scores

| Dimension | Score | Stars |
|---|---:|---|
| identity | 100.0 | ★★★★★★★★★★ |
| location | 90.0 | ★★★★★★★★★ |
| contact | 67.9 | ★★★★★★★ |
| phone_kind | 100.0 | ★★★★★★★★★★ |
| coordinates | 86.7 | ★★★★★★★★★ |
| league | 93.3 | ★★★★★★★★★ |

## Per-club details

| slug | tier | overall | issues |
|---|---:|---:|---|
| dinamo-zagreb | T1 | 1.00 | — |
| kurilovec-velika-gorica | T4 | 1.00 | founded_year=2018 reflects rename year (NK Udarnik -> NK Kurilovec); club tradition dates to 1948 per own history page |
| tomislav-d | T6 | 1.00 | no issues; club confirmed in Berek, BBŽ county; relegated from Elitna ŽNL after 2023/24 to 2. ŽNL BBŽ — matches T6/T7 listing; Facebook page verified |
| rijeka | T1 | 1.00 | — |
| dubrava-z | T8 | 1.00 | — |
| dubravcan-dd | T6 | 0.92 | x_url is a twitter share intent link (twitter.com/home?status=...semafor.hns.family) not a real club profile - aggregator/share leak per rubric |
| garic-g | T5 | 0.92 | website znsvpz.hr is a county FA aggregator listing, not the club's own site |
| zadar | T3 | 0.90 | league field shows both T3 (2021/22 stale) and T4 (25/26); current 25/26 is 3. NL Jug which is tier 3 per HNS, so T4 label looks incorrect |
| split | T3 | 0.90 | club is RNK Split 1912 re-established May 2024, currently in 5th tier per Wikipedia/sources; tier field says 3 with T3 2021/22 historical and T6 1.ŽNL SDŽ — mismatch with reported current 5th tier; contact details and website all verified clean and official |
| primorac-biograd-na-moru | T4 | 0.90 | x_url is a twitter.com/home?status= share link, not the club's actual Twitter account |
| trnski | T6 | 0.83 | phone, email (financije@nova-raca.hr), and website all belong to Općina Nova Rača municipality, not the football club |
| psunj-sokol | T5 | 0.83 | phone +38535371001 and email opcina.okucani@opcokucani.tcloud.hr belong to Općina Okučani (municipality), not the football club — clear contact leak to municipal office |
| vukovar-1991-osijek | T1 | 0.80 | city field says Osijek but 2025/26 home games are played at Stadion HNK Cibalia in Vinkovci, not Stadion Gradski vrt in Osijek; coordinates (45.5453, 18.6953) point to Vukovar (registered seat) rather than current home venue — acceptable edge case but inconsistent with stadium_name field which lists Osijek's Gradski vrt |
| adriatic | T7 | 0.70 | city field is empty (only county provided) — club is based in Split at Mostarska 72 and plays at Park mladeži (~43.519, 16.444); given coordinates 43.5589/16.3606 point to Kaštel area, >5km from actual home pitch; official site nkadriatic.hr verified |
| poljana | T7 | 0.67 | address postcode 34543 belongs to Poljana in Požeško-Slavonska county, not SMŽ Poljana near Kutina (mismatch); email danijel.vincetic@hep.hr is a personal HEP corporate address not a club address; phone +38534... uses 034 area code (Požega) not SMŽ - cross-county leak suggests data merged from wrong Poljana |
