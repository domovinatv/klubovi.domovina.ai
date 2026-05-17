-- Manual geocoding for the 15 clubs Nominatim couldn't place.
-- Generated 2026-05-17 from data/clubs.db.
-- APPLIED on 2026-05-17 — coordinates filled in via web research by 3 parallel
-- subagents (Croatian football news + Wikipedia + HNS Semafor + OSM lookup).
-- Re-runnable as a record of provenance; idempotent UPDATEs.
--
-- Confidence:
--   high   = village/town identified from official or Wikipedia source
--   medium = club known to be displaced or based in a sub-locality
-- Bounds verified: lat 42.0-46.6, lng 13.0-19.5 (Croatia).

BEGIN TRANSACTION;

-- HNK Konavljanin (Dubrovačko-neretvanska) — village center Čilipi
UPDATE clubs SET lat = 42.549539, lng = 18.281587, updated_at = CURRENT_TIMESTAMP WHERE slug = 'konavljanin';

-- NK Ekonomik (Sisačko-moslavačka) — Donja Vlahinička near Popovača; source: HNS Semafor
UPDATE clubs SET lat = 45.5834415, lng = 16.5959794, updated_at = CURRENT_TIMESTAMP WHERE slug = 'ekonomik';

-- NK HOŠK (Osječko-baranjska) — Gašinci in Satnica Đakovačka; source: Wikipedia
UPDATE clubs SET lat = 45.3350343, lng = 18.3116310, updated_at = CURRENT_TIMESTAMP WHERE slug = 'hosk';

-- NK Hrvatski Bojovnik (Koprivničko-križevačka) — Mokrice Miholečke; source: HNS Semafor
UPDATE clubs SET lat = 46.055000, lng = 16.381944, updated_at = CURRENT_TIMESTAMP WHERE slug = 'hrvatski-bojovnik';

-- NK Janjevo (Šibensko-kninska) — displaced community in Kistanje; source: Wikipedia
UPDATE clubs SET lat = 43.9805404, lng = 15.9619568, updated_at = CURRENT_TIMESTAMP WHERE slug = 'janjevo';

-- NK Kraljevčan 38 (Međimurska) — Donji Kraljevec village center
UPDATE clubs SET lat = 46.370500, lng = 16.654970, updated_at = CURRENT_TIMESTAMP WHERE slug = 'kraljevcan-38';

-- NK Parasan (Požeško-slavonska) — Golobrdci near Požega; source: sport-pozega
UPDATE clubs SET lat = 45.3767231, lng = 17.6620291, updated_at = CURRENT_TIMESTAMP WHERE slug = 'parasan';

-- NK Prekodravac (Koprivničko-križevačka) — Ždala in Gola municipality; source: Wikipedia
UPDATE clubs SET lat = 46.169138, lng = 17.141775, updated_at = CURRENT_TIMESTAMP WHERE slug = 'prekodravac';

-- NK Rusin (Vukovarsko-srijemska) — Mikluševci Ruthenian minority village; source: Wikipedia
UPDATE clubs SET lat = 45.2512468, lng = 19.0846544, updated_at = CURRENT_TIMESTAMP WHERE slug = 'rusin';

-- NK Sabarija (no county) — Subotica Podravska, Rasinja, Koprivničko-križevačka; source: Wikipedia
UPDATE clubs SET lat = 46.1901671, lng = 16.7413231, updated_at = CURRENT_TIMESTAMP WHERE slug = 'sabarija';

-- NK Srijemac (Vukovarsko-srijemska) — Strošinci; source: Wikipedia
UPDATE clubs SET lat = 44.9157897, lng = 19.0653634, updated_at = CURRENT_TIMESTAMP WHERE slug = 'srijemac';

-- NK Strijelac (Sisačko-moslavačka) — Banova Jaruga village center
UPDATE clubs SET lat = 45.441282, lng = 16.893942, updated_at = CURRENT_TIMESTAMP WHERE slug = 'strijelac';

-- NK Tomislav Siž (Koprivničko-križevačka) — Sveti Ivan Žabno (Siž = SIŽ); source: nktomislav.hr
UPDATE clubs SET lat = 45.9464805, lng = 16.6055861, updated_at = CURRENT_TIMESTAMP WHERE slug = 'tomislav-siz';

-- NK Vatrogasac (K) (Zagrebačka) — Kobilić near Velika Gorica; source: HNS Semafor
UPDATE clubs SET lat = 45.7319711, lng = 16.1012819, updated_at = CURRENT_TIMESTAMP WHERE slug = 'vatrogasac-k';

-- NK Vatrogasac (Z) (Zagrebačka) — Zdenci Brdovečki; source: HNS Semafor
UPDATE clubs SET lat = 45.8628953, lng = 15.7540367, updated_at = CURRENT_TIMESTAMP WHERE slug = 'vatrogasac-z';

COMMIT;
