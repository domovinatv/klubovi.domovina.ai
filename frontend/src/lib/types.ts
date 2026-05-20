export interface Club {
  id: number;
  slug: string;
  canonical_name: string;
  short_name?: string;
  city?: string;
  county?: string;
  founded_year?: number;
  stadium_name?: string;
  stadium_capacity?: number;
  website?: string;
  email?: string;
  phone?: string;
  phone_kind?: "mobile" | "landline" | "other";
  phone_e164?: string;
  address?: string;
  fb_url?: string;
  ig_url?: string;
  x_url?: string;
  president?: string;
  president_role?: string;
  lat?: number;
  lng?: number;
  semafor_url?: string;
  sofascore_url?: string;
  registry_url?: string;
  oib?: string;
  top_tier?: number;
  top_league_id?: number;
  top_league_name?: string;
  logo?: string;
}

export interface League {
  id: number;
  name: string;
  tier: number;
  county?: string;
  parent_id?: number;
  club_count: number;
}

export interface County {
  name: string;
  n: number;
}

export interface GlobalStats {
  total: number;
  with_city: number;
  with_county: number;
  with_geo: number;
  can_sms: number;
  can_call: number;
  can_email: number;
  can_mail: number;
  can_web: number;
  full_contact: number;
  unreachable: number;
  with_founded: number;
  with_stadium: number;
  with_president: number;
  with_oib: number;
}

export interface Stats {
  global: GlobalStats;
  tiers: Array<{ tier: number; n: number }>;
}

export interface ClubSeason {
  season: string;
  source: string;
  league_id: number;
  league_name: string;
  tier: number;
  county?: string;
}

export interface ClubDetail {
  id: number;
  slug: string;
  seasons: ClubSeason[];
  aliases: Array<{ alias: string; source?: string }>;
}
