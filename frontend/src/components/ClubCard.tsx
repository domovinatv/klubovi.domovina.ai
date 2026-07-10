import { Link } from "react-router-dom";
import { Globe, Mail, MessageCircle, Phone, type LucideIcon } from "lucide-react";
import type { Club } from "@/lib/types";
import { ClubLogo } from "./ClubLogo";
import { TierBadge } from "./TierBadge";

function ContactDots({ c }: { c: Club }) {
  const items: Array<{ ok: boolean; label: string; Icon: LucideIcon }> = [
    { ok: c.phone_kind === "mobile", label: "Mobitel", Icon: MessageCircle },
    { ok: !!c.phone, label: "Telefon", Icon: Phone },
    { ok: !!c.email, label: "Email", Icon: Mail },
    {
      ok: !!(c.website || c.fb_url || c.ig_url),
      label: "Web/društvene",
      Icon: Globe,
    },
  ];
  return (
    <div className="flex items-center gap-1.5 text-xs">
      {items.map((it) => (
        <span
          key={it.label}
          title={`${it.label}: ${it.ok ? "da" : "ne"}`}
          className={
            "inline-flex items-center justify-center w-5 h-5 rounded-full transition-colors " +
            (it.ok
              ? "bg-emerald-50 text-emerald-700"
              : "bg-surface text-muted/50")
          }
        >
          <it.Icon size={12} strokeWidth={2.2} />
        </span>
      ))}
    </div>
  );
}

export function ClubCard({ club }: { club: Club }) {
  return (
    <Link
      to={`/klub/${club.slug}`}
      className="card-hover p-4 flex gap-4 items-center group no-underline"
    >
      <ClubLogo club={club} size={56} />
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="font-semibold text-navy truncate group-hover:text-flag-red transition-colors">
            {club.canonical_name}
          </h3>
          <TierBadge tier={club.top_tier} withLabel={false} size="xs" />
        </div>
        <div className="text-xs text-muted truncate mt-0.5">
          {club.city || "—"}
          {club.county && ` · ${club.county.replace(" županija", "")}`}
          {club.top_league_name && ` · ${club.top_league_name}`}
        </div>
        <div className="mt-2">
          <ContactDots c={club} />
        </div>
      </div>
    </Link>
  );
}
