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

/** Brandirani self-custody novčanik kluba (wallet prototip, wildcard *.ff.hr). */
export function walletUrl(club: Pick<Club, "slug">): string {
  return `https://${club.slug}.ff.hr`;
}

/**
 * Deep-link to the exact udruga detail page in the government register.
 *
 * registri-npo-mpu.gov.hr is a Vaadin app: its `#!udruga-detalji/{token}`
 * route takes a base64-serialized filter+selection state, NOT a plain id.
 * The dead `#!udruge/detalji/{UDR_ID}` link we used to store just bounces to
 * the search form. We reverse-engineered the token — it is fully derivable
 * from (OIB, UDR_ID): the OIB search filter plus the selected row's UDR_ID
 * zigzag-varint-encoded. Verified byte-exact against real captured tokens and
 * confirmed live: after the one captcha the site shows the correct club.
 *
 * Returns null unless we have both OIB and a numeric UDR_ID (from registry_url).
 */
export function udrugaDetailUrl(
  club: Pick<Club, "oib" | "registry_url">,
): string | null {
  const oib = club.oib;
  const m = club.registry_url?.match(/detalji\/(\d+)/);
  if (!oib || !m) return null;
  const udrId = parseInt(m[1], 10);

  const bytes: number[] = [0xf2, 7, 1, 0, 0, 1, 0, 1, 0, 1];
  const pushStr = (s: string) => {
    for (let i = 0; i < s.length; i++) {
      const last = i === s.length - 1;
      bytes.push(s.charCodeAt(i) | (last ? 0x80 : 0)); // high bit = terminator
    }
  };
  pushStr(oib);
  bytes.push(0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1);
  pushStr("oib");
  bytes.push(0x02, 0x01);
  // zigzag varint of the selected UDR_ID (positive → id*2)
  let z = udrId * 2;
  do {
    const b = z & 0x7f;
    z = Math.floor(z / 128);
    bytes.push(z ? b | 0x80 : b);
  } while (z);

  const b64 = btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  return `https://registri-npo-mpu.gov.hr/#!udruga-detalji/${b64}`;
}

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
