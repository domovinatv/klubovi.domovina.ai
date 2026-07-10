import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { loadClubDetail, loadClubs, logoUrl, logoSrcSet } from "@/lib/data";
import type { Club, ClubDetail } from "@/lib/types";
import { PageSpinner } from "@/components/PageSpinner";
import { TierBadge } from "@/components/TierBadge";

export default function ClubRoute() {
  const { slug = "" } = useParams();
  const [club, setClub] = useState<Club | null>(null);
  const [detail, setDetail] = useState<ClubDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setClub(null);
    setDetail(null);
    setError(null);
    Promise.all([loadClubs(), loadClubDetail(slug)])
      .then(([clubs, d]) => {
        if (!active) return;
        const c = clubs.find((x) => x.slug === slug);
        if (!c) {
          setError("Klub nije pronađen.");
          return;
        }
        setClub(c);
        setDetail(d);
        document.title = `${c.canonical_name} · DOMOVINA Klubovi`;
      })
      .catch(() => active && setError("Klub nije pronađen."));
    return () => {
      active = false;
    };
  }, [slug]);

  if (error) {
    return (
      <div className="container-page py-16 text-center">
        <h1 className="text-2xl font-bold text-navy">{error}</h1>
        <Link to="/" className="btn-primary mt-6 inline-flex">
          ← Popis klubova
        </Link>
      </div>
    );
  }

  if (!club || !detail) return <PageSpinner />;

  const lg = logoUrl(club);

  return (
    <article className="container-page py-6 sm:py-10">
      <Link to="/" className="text-sm text-muted hover:text-flag-red inline-block mb-4">
        ← Natrag na popis
      </Link>

      <div className="card overflow-hidden">
        <div className="p-6 sm:p-8 flex flex-col sm:flex-row items-start gap-6 border-b border-border bg-gradient-to-br from-surface to-white">
          <div className="w-24 h-24 sm:w-32 sm:h-32 rounded-DEFAULT bg-white border border-border grid place-items-center overflow-hidden shadow-card flex-shrink-0">
            {lg ? (
              <img
                src={lg}
                srcSet={logoSrcSet(club)}
                sizes="(min-width: 640px) 128px, 96px"
                alt=""
                className="w-full h-full object-contain p-2"
              />
            ) : (
              <span className="text-6xl">⚽</span>
            )}
          </div>
          <div className="flex-1 min-w-0">
            <h1 className="text-2xl sm:text-3xl font-extrabold text-navy text-balance">
              {club.canonical_name}
            </h1>
            {club.short_name && club.short_name !== club.canonical_name && (
              <div className="text-sm text-muted mt-1">
                Kraći naziv: <span className="font-medium">{club.short_name}</span>
              </div>
            )}
            <div className="mt-3 flex flex-wrap gap-2 items-center text-sm">
              <TierBadge tier={club.top_tier} size="md" />
              {club.top_league_name && (
                <Link
                  to={`/liga/${club.top_league_id}`}
                  className="pill !text-navy hover:!text-flag-red"
                >
                  {club.top_league_name}
                </Link>
              )}
              {club.city && (
                <span className="pill">📍 {club.city}</span>
              )}
              {club.county && (
                <Link to={`/zupanija/${encodeURIComponent(club.county)}`} className="pill !text-navy">
                  🏞 {club.county.replace(" županija", "")}
                </Link>
              )}
              {club.founded_year && (
                <span className="pill">🎂 {club.founded_year}.</span>
              )}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 divide-y lg:divide-y-0 lg:divide-x divide-border">
          <ContactPanel club={club} />
          <FactsPanel club={club} />
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-4 mt-4">
        <LeaguesPanel detail={detail} />
        {detail.aliases.length > 0 && <AliasesPanel detail={detail} />}
      </div>

      <SourcePanel club={club} />
    </article>
  );
}

function ContactPanel({ club }: { club: Club }) {
  return (
    <div className="p-6 space-y-3">
      <h2 className="field-label">Kontakt</h2>
      {club.address && <Row k="Adresa" v={club.address} />}
      {club.phone && (
        <Row
          k={
            club.phone_kind === "mobile"
              ? "📱 Mobitel"
              : club.phone_kind === "landline"
                ? "☎️ Fiksni"
                : "Telefon"
          }
          v={
            <a href={`tel:${club.phone_e164 || club.phone}`} className="text-navy hover:text-flag-red">
              {club.phone}
            </a>
          }
        />
      )}
      {club.email && (
        <Row
          k="Email"
          v={
            <a href={`mailto:${club.email}`} className="text-navy hover:text-flag-red break-all">
              {club.email}
            </a>
          }
        />
      )}
      {club.website && (
        <Row
          k="Web"
          v={
            <a href={club.website} target="_blank" rel="noopener" className="break-all">
              {club.website}
            </a>
          }
        />
      )}
      {club.president && (
        <Row
          k="Predsjednik"
          v={
            <>
              {club.president}
              {club.president_role && (
                <span className="text-xs text-muted ml-1">({club.president_role})</span>
              )}
            </>
          }
        />
      )}

      <div className="flex gap-2 pt-2 flex-wrap">
        {club.fb_url && (
          <a href={club.fb_url} target="_blank" rel="noopener" className="btn-ghost !text-blue-700 !border-blue-200 hover:!bg-blue-50">
            Facebook
          </a>
        )}
        {club.ig_url && (
          <a href={club.ig_url} target="_blank" rel="noopener" className="btn-ghost !text-pink-700 !border-pink-200 hover:!bg-pink-50">
            Instagram
          </a>
        )}
        {club.x_url && (
          <a href={club.x_url} target="_blank" rel="noopener" className="btn-ghost">
            X
          </a>
        )}
      </div>

      {!club.phone && !club.email && !club.address && !club.website && !club.fb_url && (
        <p className="text-sm text-muted italic">Nema poznatih kontaktnih podataka.</p>
      )}
    </div>
  );
}

function FactsPanel({ club }: { club: Club }) {
  return (
    <div className="p-6 space-y-3">
      <h2 className="field-label">Klub</h2>
      {club.stadium_name && (
        <Row
          k="Stadion"
          v={
            <>
              {club.stadium_name}
              {club.stadium_capacity ? (
                <span className="text-xs text-muted ml-1">
                  ({club.stadium_capacity.toLocaleString("hr-HR")} mjesta)
                </span>
              ) : null}
            </>
          }
        />
      )}
      {club.founded_year && <Row k="Osnovan" v={`${club.founded_year}.`} />}
      {club.oib && <Row k="OIB" v={<span className="font-mono text-sm">{club.oib}</span>} />}
      {club.lat != null && club.lng != null && (
        <Row
          k="Koordinate"
          v={
            <a
              href={`https://www.openstreetmap.org/?mlat=${club.lat}&mlon=${club.lng}#map=15/${club.lat}/${club.lng}`}
              target="_blank"
              rel="noopener"
              className="font-mono text-sm"
            >
              {club.lat.toFixed(5)}, {club.lng.toFixed(5)}
            </a>
          }
        />
      )}
    </div>
  );
}

function LeaguesPanel({ detail }: { detail: ClubDetail }) {
  if (detail.seasons.length === 0) return null;
  return (
    <section className="card p-6">
      <h2 className="field-label">Lige kroz sezone</h2>
      <ul className="mt-2 space-y-1.5 text-sm">
        {detail.seasons.map((s) => (
          <li key={`${s.league_id}-${s.season}`} className="flex items-center gap-2 justify-between">
            <Link
              to={`/liga/${s.league_id}`}
              className="text-navy hover:text-flag-red truncate"
            >
              {s.league_name}
            </Link>
            <span className="text-muted tabular-nums text-xs">{s.season}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function AliasesPanel({ detail }: { detail: ClubDetail }) {
  return (
    <section className="card p-6">
      <h2 className="field-label">Drugi nazivi</h2>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {detail.aliases.map((a, i) => (
          <span key={i} className="pill">{a.alias}</span>
        ))}
      </div>
    </section>
  );
}

function SourcePanel({ club }: { club: Club }) {
  const links: Array<{ label: string; href: string }> = [];
  if (club.semafor_url) links.push({ label: "HNS Semafor", href: club.semafor_url });
  if (club.sofascore_url) links.push({ label: "SofaScore", href: club.sofascore_url });
  if (club.registry_url) links.push({ label: "Registar udruga", href: club.registry_url });
  if (links.length === 0) return null;
  return (
    <section className="mt-4 card p-4">
      <div className="field-label">Izvori</div>
      <div className="flex flex-wrap gap-2">
        {links.map((l) => (
          <a key={l.href} href={l.href} target="_blank" rel="noopener" className="btn-ghost text-xs">
            {l.label} ↗
          </a>
        ))}
      </div>
    </section>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="text-sm">
      <span className="text-muted text-xs uppercase tracking-wide">{k}:</span>{" "}
      <span className="text-navy-700">{v}</span>
    </div>
  );
}
