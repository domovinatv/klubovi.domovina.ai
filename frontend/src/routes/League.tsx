import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { loadClubs, loadLeagues } from "@/lib/data";
import type { Club, League } from "@/lib/types";
import { ClubCard } from "@/components/ClubCard";
import { TierBadge } from "@/components/TierBadge";
import { PageSpinner } from "@/components/PageSpinner";

export default function LeagueRoute() {
  const { id = "" } = useParams();
  const leagueId = Number(id);
  const [clubs, setClubs] = useState<Club[] | null>(null);
  const [leagues, setLeagues] = useState<League[] | null>(null);

  useEffect(() => {
    Promise.all([loadClubs(), loadLeagues()]).then(([c, l]) => {
      setClubs(c);
      setLeagues(l);
    });
  }, []);

  const league = leagues?.find((l) => l.id === leagueId);
  const filtered = useMemo(() => {
    if (!clubs || !league) return [];
    return clubs.filter((c) => c.top_league_id === leagueId);
  }, [clubs, league, leagueId]);

  if (!clubs || !leagues) return <PageSpinner />;
  if (!league) {
    return (
      <div className="container-page py-16 text-center">
        <h1 className="text-2xl font-bold text-navy">Nepoznata liga</h1>
        <Link to="/" className="btn-primary mt-6 inline-flex">
          ← Popis klubova
        </Link>
      </div>
    );
  }

  return (
    <section className="container-page py-6 sm:py-10">
      <Link to="/" className="text-sm text-muted hover:text-flag-red inline-block mb-4">
        ← Natrag na popis
      </Link>

      <div className="card p-6 mb-6 bg-gradient-to-br from-surface to-white">
        <div className="flex items-center gap-3 mb-2">
          <TierBadge tier={league.tier} size="md" />
          {league.county && (
            <Link to={`/zupanija/${encodeURIComponent(league.county)}`} className="pill !text-navy">
              {league.county.replace(" županija", "")}
            </Link>
          )}
        </div>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-navy">
          {league.name}
        </h1>
        <p className="text-muted mt-2">
          <span className="font-medium text-navy">{filtered.length}</span> klubova
          trenutno svrstanih ovdje kao najjača liga
          {league.club_count > filtered.length && (
            <> · ukupno povijesno: {league.club_count}</>
          )}
        </p>
      </div>

      {filtered.length === 0 ? (
        <div className="card p-8 text-center text-muted">
          Nema klubova trenutno svrstanih u ovu ligu kao najjaču.
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-3">
          {filtered.map((c) => (
            <ClubCard key={c.id} club={c} />
          ))}
        </div>
      )}
    </section>
  );
}
