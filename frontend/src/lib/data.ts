import type { Club, ClubDetail, County, League, Stats } from "./types";

const memo = new Map<string, Promise<unknown>>();

function fetchJson<T>(url: string): Promise<T> {
  const cached = memo.get(url) as Promise<T> | undefined;
  if (cached) return cached;
  const p = fetch(url, { credentials: "omit" }).then((r) => {
    if (!r.ok) throw new Error(`${url} → ${r.status}`);
    return r.json() as Promise<T>;
  });
  memo.set(url, p);
  return p;
}

export const loadClubs = () => fetchJson<Club[]>("/data/clubs.json");
export const loadLeagues = () => fetchJson<League[]>("/data/leagues.json");
export const loadCounties = () => fetchJson<County[]>("/data/counties.json");
export const loadStats = () => fetchJson<Stats>("/data/stats.json");
export const loadClubDetail = (slug: string) =>
  fetchJson<ClubDetail>(`/data/clubs/${slug}.json`);

const DIACRITIC_RE = /[\u0300-\u036f]/g;

export function deburr(s: string): string {
  return s.normalize("NFKD").replace(DIACRITIC_RE, "").toLowerCase();
}

const LOGO_CDN = "https://c.ff.hr";

export function logoUrl(club: Pick<Club, "logo" | "slug">): string | null {
  if (!club.logo) return null;
  return `${LOGO_CDN}/logos/${club.logo}`;
}

/**
 * srcset over the CDN size ladder (192/256/512/1024). Tiers exist only where
 * the source image honestly fills them, so the browser picks the best real
 * resolution for the rendered size × devicePixelRatio and never upscales a
 * tiny crest into a blurry big one.
 */
export function logoSrcSet(
  club: Pick<Club, "logo" | "slug" | "logo_sizes">,
): string | undefined {
  if (!club.logo || !club.logo_sizes?.length) return undefined;
  return club.logo_sizes
    .map((s) => `${LOGO_CDN}/logos/${s}/${club.slug}.png ${s}w`)
    .join(", ");
}
