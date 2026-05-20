import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { loadClubs, loadCounties, loadStats } from "@/lib/data";
import type { Club, County, Stats } from "@/lib/types";
import {
  applyFilter,
  EMPTY_FILTER,
  readFilterFromSearchParams,
  writeFilterToSearchParams,
  type ClubFilter,
} from "@/lib/filter";
import { FilterPanel } from "@/components/FilterPanel";
import { ClubCard } from "@/components/ClubCard";
import { PageSpinner } from "@/components/PageSpinner";

const PAGE_SIZE = 60;

export default function Home() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [clubs, setClubs] = useState<Club[] | null>(null);
  const [counties, setCounties] = useState<County[] | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [page, setPage] = useState(1);

  const filter = useMemo<ClubFilter>(
    () => readFilterFromSearchParams(searchParams),
    [searchParams],
  );

  useEffect(() => {
    Promise.all([loadClubs(), loadCounties(), loadStats()]).then(([c, co, s]) => {
      setClubs(c);
      setCounties(co);
      setStats(s);
    });
  }, []);

  useEffect(() => {
    setPage(1);
  }, [searchParams]);

  if (!clubs || !counties || !stats) return <PageSpinner />;

  const filtered = applyFilter(clubs, filter);
  const visible = filtered.slice(0, page * PAGE_SIZE);
  const hasMore = visible.length < filtered.length;

  const updateFilter = (next: ClubFilter) => {
    setSearchParams(writeFilterToSearchParams(next), { replace: true });
  };

  return (
    <>
      <Hero stats={stats} />

      <section className="container-page mt-8 mb-16 grid gap-6 lg:grid-cols-[280px_1fr] 2xl:grid-cols-[320px_1fr]">
        <FilterPanel
          filter={filter}
          onChange={updateFilter}
          onReset={() => updateFilter(EMPTY_FILTER)}
          counties={counties}
          stats={stats}
        />

        <div>
          <ListHeader
            shown={visible.length}
            total={filtered.length}
            filter={filter}
          />
          {filtered.length === 0 ? (
            <Empty />
          ) : (
            <>
              <div className="grid sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-3">
                {visible.map((c) => (
                  <ClubCard key={c.id} club={c} />
                ))}
              </div>
              {hasMore && (
                <div className="mt-6 flex justify-center">
                  <button
                    onClick={() => setPage((p) => p + 1)}
                    className="btn-ghost"
                  >
                    Učitaj još ({filtered.length - visible.length})
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </section>
    </>
  );
}

function Hero({ stats }: { stats: Stats }) {
  const g = stats.global;
  return (
    <section className="border-b border-border bg-gradient-to-b from-surface to-white">
      <div className="container-page py-12 sm:py-16">
        <div className="max-w-3xl">
          <div className="pill mb-4">
            🇭🇷 Otvoreni podaci · {g.total.toLocaleString("hr-HR")} klubova
          </div>
          <h1 className="text-balance text-3xl sm:text-5xl font-extrabold tracking-tight text-navy">
            Svi hrvatski nogometni klubovi
            <span className="text-flag-red"> na jednom mjestu</span>
          </h1>
          <p className="mt-4 text-lg text-muted leading-relaxed text-balance">
            Od SuperSport HNL-a do 3. ŽNL — kontakti, lige, županije, koordinate.
            Pretraži, filtriraj, izvezi.
          </p>
        </div>
        <div className="mt-8 grid grid-cols-2 sm:grid-cols-4 gap-3 max-w-3xl 2xl:max-w-5xl">
          <Stat label="Klubova" value={g.total} accent />
          <Stat label="S koordinatama" value={g.with_geo} suffix={` (${pct(g.with_geo, g.total)})`} />
          <Stat label="S kontaktom" value={g.can_call} suffix={` (${pct(g.can_call, g.total)})`} />
          <Stat label="Pun kontakt" value={g.full_contact} suffix={` (${pct(g.full_contact, g.total)})`} />
        </div>
      </div>
    </section>
  );
}

function pct(a: number, b: number): string {
  if (!b) return "0%";
  return `${Math.round((100 * a) / b)}%`;
}

function Stat({
  label,
  value,
  suffix,
  accent,
}: {
  label: string;
  value: number;
  suffix?: string;
  accent?: boolean;
}) {
  return (
    <div className="card p-4">
      <div className="field-label">{label}</div>
      <div
        className={`text-2xl sm:text-3xl font-extrabold tabular-nums ${
          accent ? "text-flag-red" : "text-navy"
        }`}
      >
        {value.toLocaleString("hr-HR")}
      </div>
      {suffix && <div className="text-xs text-muted mt-0.5">{suffix}</div>}
    </div>
  );
}

function ListHeader({
  shown,
  total,
  filter,
}: {
  shown: number;
  total: number;
  filter: ClubFilter;
}) {
  const active =
    filter.q ||
    filter.tier ||
    filter.county ||
    filter.hasMobile ||
    filter.hasLandline ||
    filter.hasEmail ||
    filter.onlyFull;
  return (
    <div className="flex items-baseline justify-between mb-4 gap-3 flex-wrap">
      <div>
        <h2 className="text-lg font-bold text-navy">
          {total.toLocaleString("hr-HR")}{" "}
          <span className="text-muted font-medium">
            {total === 1 ? "klub" : "klubova"}
          </span>
          {active && <span className="text-muted text-sm"> (filtrirano)</span>}
        </h2>
        {total > 0 && (
          <div className="text-xs text-muted">
            Prikazano {shown.toLocaleString("hr-HR")}
          </div>
        )}
      </div>
    </div>
  );
}

function Empty() {
  return (
    <div className="card p-12 text-center text-muted">
      <div className="text-5xl mb-3">⚽</div>
      <div className="font-medium text-navy">Nijedan klub ne odgovara filterima.</div>
      <div className="text-sm mt-1">Resetiraj filtere i pokušaj ponovno.</div>
    </div>
  );
}
