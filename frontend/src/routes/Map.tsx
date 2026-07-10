import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl, { type StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Link } from "react-router-dom";
import { loadClubs, loadStats, logoUrl, logoSrcSet } from "@/lib/data";
import { Shield } from "lucide-react";
import type { Club, Stats } from "@/lib/types";
import { PageSpinner } from "@/components/PageSpinner";
import { TierBadge } from "@/components/TierBadge";

const TIER_COLORS: Record<number, string> = {
  1: "#FF0000",
  2: "#F97316",
  3: "#FBBF24",
  4: "#FDE047",
  5: "#86EFAC",
  6: "#5EEAD4",
  7: "#7DD3FC",
  8: "#94A3B8",
};

// CARTO Voyager — clean light basemap, no API key
const CARTO_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    carto: {
      type: "raster",
      tiles: [
        "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png",
        "https://b.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png",
        "https://c.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png",
      ],
      tileSize: 256,
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · © <a href="https://carto.com/attributions">CARTO</a>',
    },
  },
  layers: [{ id: "carto", type: "raster", source: "carto" }],
  // Glyphs su nužni za symbol layer (cluster count). Demotiles je javni
  // MapLibre glyph endpoint, fontstack "Noto Sans Regular" je tamo dostupan.
  glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
};

export default function MapView() {
  const [clubs, setClubs] = useState<Club[] | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [selected, setSelected] = useState<Club | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);

  useEffect(() => {
    Promise.all([loadClubs(), loadStats()]).then(([c, s]) => {
      setClubs(c);
      setStats(s);
    });
  }, []);

  const geoClubs = useMemo(
    () => (clubs ? clubs.filter((c) => c.lat != null && c.lng != null) : []),
    [clubs],
  );

  useEffect(() => {
    if (!containerRef.current || !geoClubs.length || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: CARTO_STYLE,
      center: [16.5, 45.1],
      zoom: 6.5,
      attributionControl: { compact: true },
    });
    mapRef.current = map;

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    const geojson: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: geoClubs.map((c) => ({
        type: "Feature",
        id: c.id,
        geometry: { type: "Point", coordinates: [c.lng!, c.lat!] },
        properties: {
          slug: c.slug,
          name: c.canonical_name,
          tier: c.top_tier ?? 8,
        },
      })),
    };

    map.on("load", () => {
      map.addSource("clubs", {
        type: "geojson",
        data: geojson,
        cluster: true,
        clusterRadius: 40,
        clusterMaxZoom: 11,
      });

      map.addLayer({
        id: "clusters",
        type: "circle",
        source: "clubs",
        filter: ["has", "point_count"],
        paint: {
          "circle-color": "#002F6C",
          "circle-opacity": 0.85,
          "circle-stroke-color": "#FFFFFF",
          "circle-stroke-width": 2,
          "circle-radius": [
            "step",
            ["get", "point_count"],
            16,
            10,
            20,
            50,
            26,
            150,
            34,
          ],
        },
      });
      map.addLayer({
        id: "cluster-count",
        type: "symbol",
        source: "clubs",
        filter: ["has", "point_count"],
        layout: {
          "text-field": ["get", "point_count_abbreviated"],
          "text-font": ["Noto Sans Regular"],
          "text-size": 12,
          "text-allow-overlap": true,
        },
        paint: {
          "text-color": "#FFFFFF",
        },
      });

      map.addLayer({
        id: "points",
        type: "circle",
        source: "clubs",
        filter: ["!", ["has", "point_count"]],
        paint: {
          "circle-color": [
            "match",
            ["get", "tier"],
            1, TIER_COLORS[1],
            2, TIER_COLORS[2],
            3, TIER_COLORS[3],
            4, TIER_COLORS[4],
            5, TIER_COLORS[5],
            6, TIER_COLORS[6],
            7, TIER_COLORS[7],
            TIER_COLORS[8],
          ],
          "circle-radius": [
            "interpolate",
            ["linear"],
            ["zoom"],
            6, ["case", ["<=", ["get", "tier"], 2], 6, 3],
            10, ["case", ["<=", ["get", "tier"], 2], 10, 6],
            14, ["case", ["<=", ["get", "tier"], 2], 14, 10],
          ],
          "circle-stroke-color": "#FFFFFF",
          "circle-stroke-width": 1.5,
          "circle-opacity": 0.95,
        },
      });

      map.on("click", "clusters", (e) => {
        const feat = map.queryRenderedFeatures(e.point, {
          layers: ["clusters"],
        })[0];
        const clusterId = feat.properties?.cluster_id;
        if (clusterId == null) return;
        const src = map.getSource("clubs") as maplibregl.GeoJSONSource;
        src.getClusterExpansionZoom(clusterId).then((zoom) => {
          map.easeTo({
            center: (feat.geometry as GeoJSON.Point).coordinates as [number, number],
            zoom,
          });
        });
      });

      map.on("click", "points", (e) => {
        const feat = e.features?.[0];
        if (!feat) return;
        const id = feat.id as number;
        const c = geoClubs.find((x) => x.id === id);
        if (c) setSelected(c);
      });

      map.on("mouseenter", "clusters", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "clusters", () => (map.getCanvas().style.cursor = ""));
      map.on("mouseenter", "points", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "points", () => (map.getCanvas().style.cursor = ""));
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [geoClubs]);

  if (!clubs || !stats) return <PageSpinner />;

  return (
    <section className="container-page py-6">
      <div className="flex items-center justify-between gap-3 flex-wrap mb-4">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-navy">Karta klubova</h1>
          <p className="text-sm text-muted">
            <span className="font-medium text-navy">{geoClubs.length}</span> klubova
            lociranih od{" "}
            <span className="font-medium text-navy">{stats.global.total}</span>{" "}
            ({Math.round((100 * geoClubs.length) / stats.global.total)}%)
          </p>
        </div>
        <Legend />
      </div>

      <div className="relative">
        <div
          ref={containerRef}
          className="rounded-DEFAULT border border-border overflow-hidden"
          style={{ height: "78vh", minHeight: 480 }}
        />
        {selected && (
          <ClubPopupCard
            club={selected}
            onClose={() => setSelected(null)}
          />
        )}
      </div>
    </section>
  );
}

function Legend() {
  const tiers = [1, 2, 3, 4, 5, 6, 7, 8];
  return (
    <div className="flex items-center gap-2 flex-wrap text-xs text-muted">
      {tiers.map((t) => (
        <span key={t} className="inline-flex items-center gap-1.5">
          <span
            className="w-2.5 h-2.5 rounded-full ring-2 ring-white shadow-sm"
            style={{ background: TIER_COLORS[t] }}
          />
          T{t}
        </span>
      ))}
    </div>
  );
}

function ClubPopupCard({ club, onClose }: { club: Club; onClose: () => void }) {
  const lg = logoUrl(club);
  return (
    <div className="absolute left-4 bottom-4 right-4 sm:left-4 sm:bottom-4 sm:right-auto sm:max-w-sm card shadow-elevated p-4 flex gap-3 items-start z-10">
      <div className="w-14 h-14 grid place-items-center flex-shrink-0">
        {lg ? (
          <img
            src={lg}
            srcSet={logoSrcSet(club)}
            sizes="56px"
            alt=""
            className="max-w-full max-h-full w-auto h-auto object-contain"
          />
        ) : (
          <span className="w-full h-full rounded-sm bg-surface grid place-items-center text-muted/60"><Shield size={26} strokeWidth={1.5} /></span>
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <Link
            to={`/klub/${club.slug}`}
            className="font-semibold text-navy hover:text-flag-red truncate"
          >
            {club.canonical_name}
          </Link>
          <button
            onClick={onClose}
            aria-label="Zatvori"
            className="text-muted hover:text-navy text-xl leading-none"
          >
            ×
          </button>
        </div>
        <div className="text-xs text-muted mt-0.5">
          {club.city || "—"}
          {club.county && ` · ${club.county.replace(" županija", "")}`}
        </div>
        <div className="mt-1.5">
          <TierBadge tier={club.top_tier} />
        </div>
        {club.top_league_name && (
          <div className="text-xs text-muted mt-1">{club.top_league_name}</div>
        )}
        <Link
          to={`/klub/${club.slug}`}
          className="btn-ghost mt-3 inline-flex !px-3 !py-1.5 text-xs"
        >
          Detalji →
        </Link>
      </div>
    </div>
  );
}
