import type { County, Stats } from "@/lib/types";
import type { ClubFilter } from "@/lib/filter";

interface Props {
  filter: ClubFilter;
  onChange: (next: ClubFilter) => void;
  onReset: () => void;
  counties: County[];
  stats: Stats;
}

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

export function FilterPanel({ filter, onChange, onReset, counties, stats }: Props) {
  const set = <K extends keyof ClubFilter>(k: K, v: ClubFilter[K]) =>
    onChange({ ...filter, [k]: v });

  return (
    <aside className="lg:sticky lg:top-20 lg:self-start space-y-4">
      <div className="card p-4 space-y-4">
        <div>
          <label className="field-label" htmlFor="q">
            Pretraga
          </label>
          <input
            id="q"
            type="search"
            className="input"
            placeholder="Ime kluba, grad…"
            value={filter.q}
            onChange={(e) => set("q", e.target.value)}
          />
        </div>

        <div>
          <label className="field-label" htmlFor="tier">
            Razina (tier)
          </label>
          <select
            id="tier"
            className="input"
            value={filter.tier ?? ""}
            onChange={(e) =>
              set("tier", e.target.value ? Number(e.target.value) : undefined)
            }
          >
            <option value="">Sve razine</option>
            {stats.tiers.map((t) => (
              <option key={t.tier} value={t.tier}>
                T{t.tier} · {TIER_LABELS[t.tier]} ({t.n})
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="field-label" htmlFor="county">
            Županija
          </label>
          <select
            id="county"
            className="input"
            value={filter.county ?? ""}
            onChange={(e) => set("county", e.target.value || undefined)}
          >
            <option value="">Sve županije</option>
            {counties.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name.replace(" županija", "")} ({c.n})
              </option>
            ))}
          </select>
        </div>

        <div>
          <div className="field-label">Filtriraj po kontaktu</div>
          <div className="space-y-2 text-sm">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                className="accent-emerald-600 w-4 h-4 rounded"
                checked={filter.onlyFull}
                onChange={(e) => set("onlyFull", e.target.checked)}
              />
              <span className="font-medium text-emerald-700">
                ✓ Samo pun kontakt
              </span>
              <span className="text-muted text-xs ml-auto">
                {stats.global.full_contact}
              </span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                className="accent-navy w-4 h-4 rounded"
                checked={filter.hasMobile}
                onChange={(e) => set("hasMobile", e.target.checked)}
              />
              <span>💬 Mobitel</span>
              <span className="text-muted text-xs ml-auto">
                {stats.global.can_sms}
              </span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                className="accent-navy w-4 h-4 rounded"
                checked={filter.hasLandline}
                onChange={(e) => set("hasLandline", e.target.checked)}
              />
              <span>📞 Fiksni</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                className="accent-navy w-4 h-4 rounded"
                checked={filter.hasEmail}
                onChange={(e) => set("hasEmail", e.target.checked)}
              />
              <span>✉ Email</span>
              <span className="text-muted text-xs ml-auto">
                {stats.global.can_email}
              </span>
            </label>
          </div>
        </div>

        <div className="pt-2 border-t border-border">
          <button type="button" onClick={onReset} className="text-xs text-muted hover:text-flag-red">
            ↺ Resetiraj filtere
          </button>
        </div>
      </div>

      <div className="card p-4">
        <div className="field-label">Pokrivenost</div>
        <dl className="text-sm space-y-1.5">
          <Row label="Ukupno klubova" value={stats.global.total} bold />
          <Row
            label="✓ Pun kontakt"
            value={stats.global.full_contact}
            accent="emerald"
          />
          <Row label="💬 Mogu SMS" value={stats.global.can_sms} />
          <Row label="📞 Mogu nazvati" value={stats.global.can_call} />
          <Row label="✉ Mogu email" value={stats.global.can_email} />
          <Row label="📮 Mogu poštom" value={stats.global.can_mail} />
          <Row label="🗺 Imaju koord." value={stats.global.with_geo} />
          <Row label="∅ Nedostupni" value={stats.global.unreachable} muted />
        </dl>
      </div>
    </aside>
  );
}

function Row({
  label,
  value,
  bold,
  muted,
  accent,
}: {
  label: string;
  value: number;
  bold?: boolean;
  muted?: boolean;
  accent?: "emerald";
}) {
  return (
    <div className="flex items-center justify-between">
      <dt
        className={
          accent === "emerald"
            ? "text-emerald-700 font-medium"
            : muted
              ? "text-muted/70"
              : "text-muted"
        }
      >
        {label}
      </dt>
      <dd
        className={`tabular-nums ${bold ? "font-bold text-navy" : ""} ${
          muted ? "text-muted/70" : ""
        }`}
      >
        {value.toLocaleString("hr-HR")}
      </dd>
    </div>
  );
}
