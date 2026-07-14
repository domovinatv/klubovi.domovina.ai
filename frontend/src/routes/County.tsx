import { Mountain } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { loadClubs } from "@/lib/data";
import type { Club } from "@/lib/types";
import { ClubCard } from "@/components/ClubCard";
import { PageSpinner } from "@/components/PageSpinner";

export default function CountyRoute() {
  const { name = "" } = useParams();
  const decoded = decodeURIComponent(name);
  const [clubs, setClubs] = useState<Club[] | null>(null);

  useEffect(() => {
    loadClubs().then(setClubs);
  }, []);

  const filtered = useMemo(
    () => (clubs ? clubs.filter((c) => c.county === decoded) : []),
    [clubs, decoded],
  );

  if (!clubs) return <PageSpinner />;

  if (filtered.length === 0) {
    return (
      <div className="container-page py-16 text-center">
        <h1 className="text-2xl font-bold text-navy">Nepoznata županija</h1>
        <Link to="/" className="btn-primary mt-6 inline-flex">
          ← Popis klubova
        </Link>
      </div>
    );
  }

  const tierBreakdown = new Map<number, number>();
  for (const c of filtered) {
    if (c.top_tier) {
      tierBreakdown.set(c.top_tier, (tierBreakdown.get(c.top_tier) || 0) + 1);
    }
  }

  return (
    <section className="container-page py-6 sm:py-10">
      <Link to="/" className="text-sm text-muted hover:text-flag-red inline-block mb-4">
        ← Natrag na popis
      </Link>

      <div className="card p-6 mb-6 bg-gradient-to-br from-surface to-white">
        <div className="pill mb-2 inline-flex items-center gap-1.5"><Mountain size={13} /> Županija</div>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-navy">
          {decoded}
        </h1>
        <p className="text-muted mt-2">
          <span className="font-medium text-navy">{filtered.length}</span>{" "}
          {filtered.length === 1 ? "klub" : "klubova"}
          {tierBreakdown.size > 0 && " · po razini: "}
          {Array.from(tierBreakdown.entries())
            .sort((a, b) => a[0] - b[0])
            .map(([tier, n], i, arr) => (
              <span key={tier} className="text-navy">
                T{tier} ({n}){i < arr.length - 1 ? ", " : ""}
              </span>
            ))}
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-3">
        {filtered.map((c) => (
          <ClubCard key={c.id} club={c} />
        ))}
      </div>
    </section>
  );
}
