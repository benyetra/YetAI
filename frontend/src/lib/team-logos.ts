/** Team logos: MLB/NFL SVGs (YetiBets) + ESPN PNGs for other leagues */

import {
  ESPN_TEAM_LOGO_REGISTRY,
  type EspnLogoLeague,
} from '@/lib/team-logo-registry.generated';

export type TeamLogoLeague = 'mlb' | 'nfl' | EspnLogoLeague;

const NFL_SLUG_BY_ABBR: Record<string, string> = {
  ARI: 'arizona_cardinals',
  ATL: 'atlanta_falcons',
  BAL: 'baltimore_ravens',
  BUF: 'buffalo_bills',
  CAR: 'carolina_panthers',
  CHI: 'chicago_bears',
  CIN: 'cincinnati_bengals',
  CLE: 'cleveland_browns',
  DAL: 'dallas_cowboys',
  DEN: 'denver_broncos',
  DET: 'detroit_lions',
  GB: 'green_bay_packers',
  HOU: 'houston_texans',
  IND: 'indianapolis_colts',
  JAX: 'jacksonville_jaguars',
  KC: 'kansas_city_chiefs',
  LV: 'las_vegas_raiders',
  LAC: 'los_angeles_chargers',
  LAR: 'los_angeles_rams',
  MIA: 'miami_dolphins',
  MIN: 'minnesota_vikings',
  NE: 'new_england_patriots',
  NO: 'new_orleans_saints',
  NYG: 'new_york_giants',
  NYJ: 'new_york_jets',
  PHI: 'philadelphia_eagles',
  PIT: 'pittsburgh_steelers',
  SF: 'san_francisco_49ers',
  SEA: 'seattle_seahawks',
  TB: 'tampa_bay_buccaneers',
  TEN: 'tennessee_titans',
  WAS: 'washington_commanders',
};

const MLB_NAME_ALIASES: Record<string, string> = {
  athletics: 'athletics',
  'oakland athletics': 'athletics',
  'oakland a\'s': 'athletics',
  "oakland a's": 'athletics',
  'cleveland indians': 'cleveland_guardians',
};

const SPORT_KEY_TO_LEAGUE: Record<string, TeamLogoLeague> = {
  baseball_mlb: 'mlb',
  americanfootball_nfl: 'nfl',
  basketball_nba: 'nba',
  basketball_wnba: 'wnba',
  icehockey_nhl: 'nhl',
  soccer_epl: 'epl',
  soccer_mls: 'mls',
  soccer_uefa_champs_league: 'ucl',
  americanfootball_ncaaf: 'ncaaf',
  basketball_ncaab: 'ncaab',
};

const LEAGUE_LABEL_TO_FOLDER: Record<string, TeamLogoLeague> = {
  MLB: 'mlb',
  NFL: 'nfl',
  NBA: 'nba',
  WNBA: 'wnba',
  NHL: 'nhl',
  EPL: 'epl',
  MLS: 'mls',
  UCL: 'ucl',
  NCAAF: 'ncaaf',
  NCAAB: 'ncaab',
  'PREMIER LEAGUE': 'epl',
  'CHAMPIONS LEAGUE': 'ucl',
};

export function normalizeTeamSlug(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/['.]/g, '')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

function normalizeKey(value: string): string {
  return value.trim().toLowerCase().replace(/\./g, '');
}

export function mlbLogoSlug(teamName: string): string {
  const key = normalizeKey(teamName);
  if (MLB_NAME_ALIASES[key]) return MLB_NAME_ALIASES[key];
  return key.replace(/\s+/g, '_');
}

export function nflLogoSlug(teamNameOrAbbr: string): string | null {
  const trimmed = teamNameOrAbbr.trim();
  const upper = trimmed.toUpperCase();
  if (NFL_SLUG_BY_ABBR[upper]) return NFL_SLUG_BY_ABBR[upper];
  if (trimmed.length <= 4 && upper === trimmed) {
    return NFL_SLUG_BY_ABBR[upper] ?? null;
  }
  return trimmed.replace(/\s+/g, '_').replace(/\./g, '').toLowerCase();
}

function resolveEspnStem(
  league: EspnLogoLeague,
  name: string,
  abbr?: string,
): string | null {
  const reg = ESPN_TEAM_LOGO_REGISTRY[league];
  const slug = normalizeTeamSlug(name);
  if (slug && reg.byName[slug]) return reg.byName[slug];
  const upper = (abbr || '').trim().toUpperCase();
  if (upper && reg.byAbbr[upper]) return reg.byAbbr[upper];
  if (name.length <= 4) {
    const fromAbbr = reg.byAbbr[name.trim().toUpperCase()];
    if (fromAbbr) return fromAbbr;
  }
  return null;
}

function logoAssetPath(league: TeamLogoLeague, stem: string): string {
  if (league === 'mlb' || league === 'nfl') {
    return `/team-logos/${league}/${stem}.svg`;
  }
  return `/team-logos/${league}/${stem}.png`;
}

export function inferLogoLeague(
  league?: string,
  sportKey?: string,
): TeamLogoLeague | null {
  const leagueKey = (league || '').trim().toUpperCase();
  if (LEAGUE_LABEL_TO_FOLDER[leagueKey]) return LEAGUE_LABEL_TO_FOLDER[leagueKey];

  const sport = (sportKey || '').toLowerCase();
  if (SPORT_KEY_TO_LEAGUE[sport]) return SPORT_KEY_TO_LEAGUE[sport];
  for (const [key, folder] of Object.entries(SPORT_KEY_TO_LEAGUE)) {
    if (sport.includes(key) || sport.endsWith(`_${folder}`)) return folder;
  }
  return null;
}

export function teamLogoUrl(
  teamNameOrAbbr: string,
  opts: { league?: string; sportKey?: string; abbr?: string } = {},
): string | null {
  const name = teamNameOrAbbr.trim();
  if (!name) return null;

  const logoLeague = inferLogoLeague(opts.league, opts.sportKey);
  if (!logoLeague) return null;

  if (logoLeague === 'mlb') {
    return logoAssetPath('mlb', mlbLogoSlug(name));
  }
  if (logoLeague === 'nfl') {
    const slug = nflLogoSlug(name) ?? (opts.abbr ? nflLogoSlug(opts.abbr) : null);
    return slug ? logoAssetPath('nfl', slug) : null;
  }

  const stem = resolveEspnStem(logoLeague, name, opts.abbr);
  return stem ? logoAssetPath(logoLeague, stem) : null;
}
