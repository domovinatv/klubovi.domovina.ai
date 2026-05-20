import type { Club } from "./types";
import { deburr } from "./data";

export interface ClubFilter {
  q: string;
  tier?: number;
  county?: string;
  hasMobile: boolean;
  hasLandline: boolean;
  hasEmail: boolean;
  onlyFull: boolean;
}

export const EMPTY_FILTER: ClubFilter = {
  q: "",
  tier: undefined,
  county: undefined,
  hasMobile: false,
  hasLandline: false,
  hasEmail: false,
  onlyFull: false,
};

export function isFullContact(c: Club): boolean {
  return (
    c.phone_kind === "mobile" &&
    !!c.phone &&
    !!c.email &&
    !!c.address &&
    !!(c.website || c.fb_url || c.ig_url)
  );
}

export function applyFilter(clubs: Club[], f: ClubFilter): Club[] {
  const q = deburr(f.q.trim());
  return clubs.filter((c) => {
    if (f.tier && c.top_tier !== f.tier) return false;
    if (f.county && c.county !== f.county) return false;
    if (f.hasMobile && c.phone_kind !== "mobile") return false;
    if (f.hasLandline && c.phone_kind !== "landline") return false;
    if (f.hasEmail && !c.email) return false;
    if (f.onlyFull && !isFullContact(c)) return false;
    if (q) {
      const hay = deburr(
        `${c.canonical_name} ${c.short_name || ""} ${c.city || ""} ${c.county || ""}`,
      );
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

export function readFilterFromSearchParams(sp: URLSearchParams): ClubFilter {
  const num = (v: string | null) => (v && /^\d+$/.test(v) ? Number(v) : undefined);
  const bool = (v: string | null) => v === "1" || v === "true";
  return {
    q: sp.get("q") || "",
    tier: num(sp.get("tier")),
    county: sp.get("county") || undefined,
    hasMobile: bool(sp.get("mob")),
    hasLandline: bool(sp.get("fix")),
    hasEmail: bool(sp.get("em")),
    onlyFull: bool(sp.get("full")),
  };
}

export function writeFilterToSearchParams(f: ClubFilter): URLSearchParams {
  const sp = new URLSearchParams();
  if (f.q) sp.set("q", f.q);
  if (f.tier) sp.set("tier", String(f.tier));
  if (f.county) sp.set("county", f.county);
  if (f.hasMobile) sp.set("mob", "1");
  if (f.hasLandline) sp.set("fix", "1");
  if (f.hasEmail) sp.set("em", "1");
  if (f.onlyFull) sp.set("full", "1");
  return sp;
}
