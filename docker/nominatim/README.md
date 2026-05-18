# Local Nominatim — geocoder za bulk hrvatske podatke

Public `nominatim.openstreetmap.org` ima striktni 1 req/s limit i nije za bulk.
Lokalna instanca s HR PBF-om rješava taj problem — tisuće req/s, sub-ms
latency, bez quote-a, idealno za:

- verifikaciju svih 901 klubova (`scripts/26_verify_geo.py`)
- geocoding cijelog Registra udruga (319k subjekata) ako ikad zatreba
- eksperimentiranje sa shemama upita bez straha od ban-a

## Setup (jednom)

```bash
docker compose -f docker/nominatim/compose.yml up -d
docker compose -f docker/nominatim/compose.yml logs -f nominatim
# čekaj "Nominatim is ready" — 10-15 min za HR PBF na prosječnom laptopu
```

Sanity check:
```bash
curl 'http://localhost:8080/search?q=Ivanic-Grad&format=json&limit=1' | jq '.[0] | {display_name, lat, lon}'
```

## Korištenje iz skripti

Sve geocoding skripte poštuju `NOMINATIM_ENDPOINT` env var:

```bash
export NOMINATIM_ENDPOINT=http://localhost:8080
uv run python scripts/10_geocode_nominatim.py
uv run python scripts/26_verify_geo.py
```

Bez env vara fallback je javni Nominatim s 1 req/s throttle-om.

## Resursi

| Resurs | HR-only | Cijela Europa |
|---|---|---|
| Disk | 3-5 GB | ~500 GB |
| RAM (peak import) | ~6 GB | 64+ GB |
| RAM (steady state) | ~2 GB | ~16 GB |
| Import time | 10-15 min | par sati |

## Refresh

Geofabrik objavljuje dnevne diffe. Compose ima `REPLICATION_URL` postavljen pa
container drži DB ažuran. Ako želiš full reimport (npr. nakon major OSM
schema change):

```bash
docker compose -f docker/nominatim/compose.yml down -v
docker compose -f docker/nominatim/compose.yml up -d
```

## Switch na cijelu Europu

U `compose.yml`:
- `PBF_URL: https://download.geofabrik.de/europe-latest.osm.pbf`
- `REPLICATION_URL: https://download.geofabrik.de/europe-updates/`
- povećaj `THREADS` i `shm_size` ako CPU/RAM dopuštaju
- predvidi par sati za prvi boot

## Troubleshooting

- **`port 8080 already in use`**: drugi servis zauzima port. Promijeni
  `ports: ["8090:8080"]` i exporta `NOMINATIM_ENDPOINT=http://localhost:8090`.
- **Import zapne nakon ~30%**: gotovo uvijek RAM. Smanji `THREADS` ili daj
  Docker-u više RAM-a (Docker Desktop → Resources).
- **`Nominatim is ready` ali svaki query daje 404**: pričekaj još 2-3 min;
  indeksi se grade nakon importa. Health check je tolerantan na to.
