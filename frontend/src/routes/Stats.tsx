import { ChartColumn } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { loadCounties, loadStats } from "@/lib/data";
import type { County, Stats } from "@/lib/types";
import { PageSpinner } from "@/components/PageSpinner";

const TIER_LABELS: Record<number, string> = {
  1: "HNL",
  2: "1. NL",
  3: "3. HNL / 2. NL",
  4: "3. NL",
  5: "1. ŽNL",
  6: "2. ŽNL",
  7: "3. ŽNL",
  8: "Amaterska",
};

export default function StatsRoute() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [counties, setCounties] = useState<County[] | null>(null);

  useEffect(() => {
    Promise.all([loadStats(), loadCounties()]).then(([s, c]) => {
      setStats(s);
      setCounties(c);
    });
  }, []);

  if (!stats || !counties) return <PageSpinner />;
  const g = stats.global;

  return (
    <section className="container-page py-6 sm:py-10">
      <header className="mb-8">
        <div className="pill mb-2 inline-flex items-center gap-1.5"><ChartColumn size={13} /> Pokrivenost</div>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-navy">
          Statistika kataloga
        </h1>
        <p className="text-muted mt-2 max-w-2xl">
          Kako je popunjen katalog: koliko klubova ima koje vrste podatka.
          Postoci se računaju prema ukupnoj brojci od{" "}
          <span className="font-medium text-navy">{g.total}</span> klubova.
        </p>
      </header>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-6 gap-3">
        <StatCard label="Ukupno klubova" value={g.total} accent />
        <StatCard label="Pun kontakt" value={g.full_contact} of={g.total} emerald />
        <StatCard label="Mobitel (SMS)" value={g.can_sms} of={g.total} />
        <StatCard label="Email" value={g.can_email} of={g.total} />
        <StatCard label="Telefon (svi)" value={g.can_call} of={g.total} />
        <StatCard label="Adresa" value={g.can_mail} of={g.total} />
        <StatCard label="Koordinate" value={g.with_geo} of={g.total} />
        <StatCard label="Online prisutni" value={g.can_web} of={g.total} />
        <StatCard label="Godina osnutka" value={g.with_founded} of={g.total} />
        <StatCard label="Stadion" value={g.with_stadium} of={g.total} />
        <StatCard label="Predsjednik" value={g.with_president} of={g.total} />
        <StatCard label="OIB" value={g.with_oib} of={g.total} />
      </div>

      <h2 className="mt-12 mb-3 text-lg font-bold text-navy">Po razini natjecanja</h2>
      <div className="grid sm:grid-cols-4 lg:grid-cols-8 gap-2">
        {stats.tiers.map((t) => (
          <div
            key={t.tier}
            className="card p-3 text-center"
            style={{ borderTop: `4px solid var(--tier-${t.tier})` }}
          >
            <div className="text-xs text-muted uppercase tracking-wide">T{t.tier}</div>
            <div className="text-2xl font-extrabold text-navy tabular-nums">{t.n}</div>
            <div className="text-xs text-muted">{TIER_LABELS[t.tier]}</div>
          </div>
        ))}
      </div>

      <h2 className="mt-12 mb-3 text-lg font-bold text-navy">Po županiji</h2>
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5 gap-2">
        {counties.map((c) => (
          <Link
            key={c.name}
            to={`/zupanija/${encodeURIComponent(c.name)}`}
            className="card-hover p-3 flex items-center justify-between"
          >
            <span className="text-sm text-navy truncate">
              {c.name.replace(" županija", "")}
            </span>
            <span className="text-sm font-bold text-navy tabular-nums">{c.n}</span>
          </Link>
        ))}
      </div>
    </section>
  );
}

function StatCard({
  label,
  value,
  of,
  accent,
  emerald,
}: {
  label: string;
  value: number;
  of?: number;
  accent?: boolean;
  emerald?: boolean;
}) {
  const pct = of ? Math.round((100 * value) / of) : null;
  return (
    <div className="card p-4">
      <div className="field-label">{label}</div>
      <div
        className={`text-3xl font-extrabold tabular-nums ${
          emerald ? "text-emerald-600" : accent ? "text-flag-red" : "text-navy"
        }`}
      >
        {value.toLocaleString("hr-HR")}
      </div>
      {pct !== null && (
        <div className="mt-1">
          <div className="h-1.5 rounded-full bg-surface overflow-hidden">
            <div
              className={`h-full ${emerald ? "bg-emerald-500" : "bg-navy"}`}
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="text-xs text-muted mt-0.5 tabular-nums">{pct}%</div>
        </div>
      )}
    </div>
  );
}
