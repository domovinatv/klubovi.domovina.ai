# Pipeline verification report — 2026-05-17

Sample size: **15** clubs (stratified by tier)
**Overall pipeline reliability: 92.0 / 100**

## Dimension scores

| Dimension | Score | Stars |
|---|---:|---|
| identity | 96.7 | ★★★★★★★★★★ |
| location | 100.0 | ★★★★★★★★★★ |
| contact | 70.0 | ★★★★★★★ |
| phone_kind | 100.0 | ★★★★★★★★★★ |
| coordinates | 90.0 | ★★★★★★★★★ |
| league | 100.0 | ★★★★★★★★★★ |

## Per-club details

| slug | tier | overall | issues |
|---|---:|---:|---|
| gorica-velika-gorica | T1 | 1.00 | — |
| lucko-zagreb | T3 | 1.00 | — |
| crikvenica | T4 | 1.00 | stadium_name field contains club name instead of 'Gradski stadion Crikvenica' |
| bsk-budasevo | T6 | 1.00 | — |
| dinamo-zagreb | T1 | 1.00 | — |
| kustosija-zagreb | T3 | 1.00 | — |
| vukovar-1991-osijek | T1 | 1.00 | — |
| top | T5 | 1.00 | — |
| bsk-brdovec | T7 | 0.92 | email is private gmail (president personal) |
| sloga-s | T6 | 0.90 | slug 'sloga-s' ambiguous; contact data matches NK Sloga Čakovec, not Štrigova |
| gaj-brodanci | T8 | 0.90 | coords ~5-6km south of Brođanci village |
| croatia-g | T6 | 0.83 | website is aggregator hrvatskekarta.com, fb_url is FB sharer, x_url is Twitter share button |
| bilogora-91 | T4 | 0.80 | website is HNS Semafor profile (not club site), fb_url is FB sharer link, stadium_name is club name copy |
| dinamo-o | T7 | 0.75 | address/email/website/phone all belong to county FA (NSSMZ) office, not the club; coords in Sisak area not Odra suburb |
| rugvica-sava-1976 | T5 | 0.70 | website/fb/ig all dugoselska-kronika local news; coords ~5km south of Rugvica |
