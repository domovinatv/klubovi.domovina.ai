-- Manual geocoding for the 15 clubs that Nominatim could not place.
-- Generated 2026-05-17 from data/clubs.db.
--
-- HOW TO USE
--   For each club below:
--     1. Open the OSM (or Google) search URL.
--     2. Find the field/club on the map; right-click -> copy coordinates.
--        Croatia: lat ~42-46 (north), lng ~13-19 (east).
--     3. UNCOMMENT the UPDATE line (remove leading "-- "),
--        replace 0.0, 0.0 with the real values.
--     4. Save, then apply:  sqlite3 data/clubs.db < data/manual_geocoding.sql
--     5. Refresh /map.
--
-- Lines stay commented until you intentionally uncomment them, so running
-- the file in its template state is a no-op.

-- HNK Konavljanin
--   county:  Dubrovačko-neretvanska županija
--   address: Čilipi 70, Čilipi
--   osm:    https://www.openstreetmap.org/search?query=%C4%8Cilipi+70%2C+%C4%8Cilipi
--   google: https://www.google.com/maps/search/%C4%8Cilipi+70%2C+%C4%8Cilipi
-- UPDATE clubs SET lat = 0.0, lng = 0.0, updated_at = CURRENT_TIMESTAMP WHERE slug = 'konavljanin';

-- NK Ekonomik
--   county:  Sisačko-moslavačka županija
--   osm:    https://www.openstreetmap.org/search?query=NK+Ekonomik%2C+Sisa%C4%8Dko-moslava%C4%8Dka+%C5%BEupanija
--   google: https://www.google.com/maps/search/NK+Ekonomik%2C+Sisa%C4%8Dko-moslava%C4%8Dka+%C5%BEupanija
-- UPDATE clubs SET lat = 0.0, lng = 0.0, updated_at = CURRENT_TIMESTAMP WHERE slug = 'ekonomik';

-- NK HOŠK
--   county:  Osječko-baranjska županija
--   osm:    https://www.openstreetmap.org/search?query=NK+HO%C5%A0K%2C+Osje%C4%8Dko-baranjska+%C5%BEupanija
--   google: https://www.google.com/maps/search/NK+HO%C5%A0K%2C+Osje%C4%8Dko-baranjska+%C5%BEupanija
-- UPDATE clubs SET lat = 0.0, lng = 0.0, updated_at = CURRENT_TIMESTAMP WHERE slug = 'hosk';

-- NK Hrvatski Bojovnik
--   county:  Koprivničko-križevačka županija
--   osm:    https://www.openstreetmap.org/search?query=NK+Hrvatski+Bojovnik%2C+Koprivni%C4%8Dko-kri%C5%BEeva%C4%8Dka+%C5%BEupanija
--   google: https://www.google.com/maps/search/NK+Hrvatski+Bojovnik%2C+Koprivni%C4%8Dko-kri%C5%BEeva%C4%8Dka+%C5%BEupanija
-- UPDATE clubs SET lat = 0.0, lng = 0.0, updated_at = CURRENT_TIMESTAMP WHERE slug = 'hrvatski-bojovnik';

-- NK Janjevo
--   county:  Šibensko-kninska županija
--   osm:    https://www.openstreetmap.org/search?query=NK+Janjevo%2C+%C5%A0ibensko-kninska+%C5%BEupanija
--   google: https://www.google.com/maps/search/NK+Janjevo%2C+%C5%A0ibensko-kninska+%C5%BEupanija
-- UPDATE clubs SET lat = 0.0, lng = 0.0, updated_at = CURRENT_TIMESTAMP WHERE slug = 'janjevo';

-- NK Kraljevčan 38
--   city:    Donji Kraljevac
--   county:  Međimurska županija
--   address: Donji Kraljevac
--   osm:    https://www.openstreetmap.org/search?query=Donji+Kraljevac
--   google: https://www.google.com/maps/search/Donji+Kraljevac
-- UPDATE clubs SET lat = 0.0, lng = 0.0, updated_at = CURRENT_TIMESTAMP WHERE slug = 'kraljevcan-38';

-- NK Parasan
--   county:  Požeško-slavonska županija
--   osm:    https://www.openstreetmap.org/search?query=NK+Parasan%2C+Po%C5%BEe%C5%A1ko-slavonska+%C5%BEupanija
--   google: https://www.google.com/maps/search/NK+Parasan%2C+Po%C5%BEe%C5%A1ko-slavonska+%C5%BEupanija
-- UPDATE clubs SET lat = 0.0, lng = 0.0, updated_at = CURRENT_TIMESTAMP WHERE slug = 'parasan';

-- NK Prekodravac
--   county:  Koprivničko-križevačka županija
--   osm:    https://www.openstreetmap.org/search?query=NK+Prekodravac%2C+Koprivni%C4%8Dko-kri%C5%BEeva%C4%8Dka+%C5%BEupanija
--   google: https://www.google.com/maps/search/NK+Prekodravac%2C+Koprivni%C4%8Dko-kri%C5%BEeva%C4%8Dka+%C5%BEupanija
-- UPDATE clubs SET lat = 0.0, lng = 0.0, updated_at = CURRENT_TIMESTAMP WHERE slug = 'prekodravac';

-- NK Rusin
--   county:  Vukovarsko-srijemska županija
--   osm:    https://www.openstreetmap.org/search?query=NK+Rusin%2C+Vukovarsko-srijemska+%C5%BEupanija
--   google: https://www.google.com/maps/search/NK+Rusin%2C+Vukovarsko-srijemska+%C5%BEupanija
-- UPDATE clubs SET lat = 0.0, lng = 0.0, updated_at = CURRENT_TIMESTAMP WHERE slug = 'rusin';

-- NK Sabarija
--   osm:    https://www.openstreetmap.org/search?query=NK+Sabarija%2C+Hrvatska
--   google: https://www.google.com/maps/search/NK+Sabarija%2C+Hrvatska
-- UPDATE clubs SET lat = 0.0, lng = 0.0, updated_at = CURRENT_TIMESTAMP WHERE slug = 'sabarija';

-- NK Srijemac
--   county:  Vukovarsko-srijemska županija
--   osm:    https://www.openstreetmap.org/search?query=NK+Srijemac%2C+Vukovarsko-srijemska+%C5%BEupanija
--   google: https://www.google.com/maps/search/NK+Srijemac%2C+Vukovarsko-srijemska+%C5%BEupanija
-- UPDATE clubs SET lat = 0.0, lng = 0.0, updated_at = CURRENT_TIMESTAMP WHERE slug = 'srijemac';

-- NK Strijelac
--   county:  Sisačko-moslavačka županija
--   address: Banova Jaruga Cvjetni trg b. b., Banova Jaruga
--   osm:    https://www.openstreetmap.org/search?query=Banova+Jaruga+Cvjetni+trg+b.+b.%2C+Banova+Jaruga
--   google: https://www.google.com/maps/search/Banova+Jaruga+Cvjetni+trg+b.+b.%2C+Banova+Jaruga
-- UPDATE clubs SET lat = 0.0, lng = 0.0, updated_at = CURRENT_TIMESTAMP WHERE slug = 'strijelac';

-- NK Tomislav Siž
--   county:  Koprivničko-križevačka županija
--   osm:    https://www.openstreetmap.org/search?query=NK+Tomislav+Si%C5%BE%2C+Koprivni%C4%8Dko-kri%C5%BEeva%C4%8Dka+%C5%BEupanija
--   google: https://www.google.com/maps/search/NK+Tomislav+Si%C5%BE%2C+Koprivni%C4%8Dko-kri%C5%BEeva%C4%8Dka+%C5%BEupanija
-- UPDATE clubs SET lat = 0.0, lng = 0.0, updated_at = CURRENT_TIMESTAMP WHERE slug = 'tomislav-siz';

-- NK Vatrogasac (K)
--   county:  Zagrebačka županija
--   osm:    https://www.openstreetmap.org/search?query=NK+Vatrogasac+%28K%29%2C+Zagreba%C4%8Dka+%C5%BEupanija
--   google: https://www.google.com/maps/search/NK+Vatrogasac+%28K%29%2C+Zagreba%C4%8Dka+%C5%BEupanija
-- UPDATE clubs SET lat = 0.0, lng = 0.0, updated_at = CURRENT_TIMESTAMP WHERE slug = 'vatrogasac-k';

-- NK Vatrogasac (Z)
--   county:  Zagrebačka županija
--   osm:    https://www.openstreetmap.org/search?query=NK+Vatrogasac+%28Z%29%2C+Zagreba%C4%8Dka+%C5%BEupanija
--   google: https://www.google.com/maps/search/NK+Vatrogasac+%28Z%29%2C+Zagreba%C4%8Dka+%C5%BEupanija
-- UPDATE clubs SET lat = 0.0, lng = 0.0, updated_at = CURRENT_TIMESTAMP WHERE slug = 'vatrogasac-z';

