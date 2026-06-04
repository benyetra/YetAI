/** Team logo paths (from YetiBets/static) served under /team-logos/ */

export type TeamLogoLeague = 'mlb' | 'nfl';

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

export function inferLogoLeague(
  league?: string,
  sportKey?: string,
): TeamLogoLeague | null {
  const leagueKey = (league || '').trim().toUpperCase();
  if (leagueKey === 'MLB') return 'mlb';
  if (leagueKey === 'NFL') return 'nfl';

  const sport = (sportKey || '').toLowerCase();
  if (sport.includes('baseball_mlb') || sport.endsWith('_mlb') || sport === 'baseball_mlb') {
    return 'mlb';
  }
  if (sport.includes('americanfootball_nfl') || sport.endsWith('_nfl')) {
    return 'nfl';
  }
  return null;
}

export function teamLogoUrl(
  teamNameOrAbbr: string,
  opts: { league?: string; sportKey?: string; abbr?: string } = {},
): string | null {
  const name = teamNameOrAbbr.trim();
  if (!name) return null;

  let logoLeague = inferLogoLeague(opts.league, opts.sportKey);
  if (!logoLeague) logoLeague = inferLogoLeagueFromName(name);
  if (!logoLeague && opts.abbr && NFL_SLUG_BY_ABBR[opts.abbr.toUpperCase()]) {
    logoLeague = 'nfl';
  }

  if (logoLeague === 'mlb') {
    return `/team-logos/mlb/${mlbLogoSlug(name)}.svg`;
  }
  if (logoLeague === 'nfl') {
    const slug = nflLogoSlug(name) ?? (opts.abbr ? nflLogoSlug(opts.abbr) : null);
    return slug ? `/team-logos/nfl/${slug}.svg` : null;
  }
  return null;
}

/** Guess league from full team name when sport metadata is missing. */
function inferLogoLeagueFromName(name: string): TeamLogoLeague | null {
  const slug = mlbLogoSlug(name);
  const mlbHints = [
    'yankees',
    'red sox',
    'dodgers',
    'cubs',
    'mets',
    'guardians',
    'marlins',
    'diamondbacks',
    'padres',
    'rockies',
    'rangers',
    'rays',
    'nationals',
    'brewers',
    'twins',
    'royals',
    'tigers',
    'orioles',
    'phillies',
    'pirates',
    'braves',
    'mariners',
    'cardinals',
    'athletics',
    'angels',
    'astros',
    'giants',
    'blue jays',
    'white sox',
    'reds',
  ];
  const lower = name.toLowerCase();
  if (mlbHints.some((h) => lower.includes(h))) return 'mlb';
  if (nflLogoSlug(name)) return 'nfl';
  if (Object.values(NFL_SLUG_BY_ABBR).some((s) => s.replace(/_/g, ' ') === lower)) {
    return 'nfl';
  }
  if (slug && !lower.includes('city') && !lower.includes('united')) return 'mlb';
  return null;
}
