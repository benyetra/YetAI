import type { LeagueRules } from '@/lib/fantasy-league-rules';

const POSITION_RANGES: Record<string, [number, number]> = {
  QB: [20, 45],
  RB: [15, 40],
  WR: [12, 38],
  TE: [8, 25],
  K: [2, 6],
  DEF: [3, 8],
};

const STRONG_OFFENSES = new Set(['KC', 'BUF', 'DAL', 'SF', 'PHI', 'MIA', 'LAR']);
const WEAK_OFFENSES = new Set(['WAS', 'CHI', 'NYG', 'CAR']);

/** Keep in sync with backend/app/services/fantasy_league_format.py */
export const QB_PREMIUM_SUPERFLEX = 1.4;
export const QB_PREMIUM_2QB = 1.25;
export const TE_SCARCITY_LARGE_LEAGUE = 1.05;
export const TE_SCARCITY_LARGE_WITH_PREMIUM = 1.08;

/** FNV-1a 32-bit — stable in browser without crypto async. */
export function stableUnit(seed: string): number {
  let hash = 2166136261;
  for (let i = 0; i < seed.length; i += 1) {
    hash ^= seed.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) / 0xffffffff;
}

function ageMultiplier(age: number): number {
  if (age <= 24) return 1.1;
  if (age <= 27) return 1.0;
  if (age <= 30) return 0.95;
  return 0.8;
}

function teamMultiplier(team: string): number {
  if (STRONG_OFFENSES.has(team)) return 1.05;
  if (WEAK_OFFENSES.has(team)) return 0.95;
  return 1.0;
}

function scoringMultiplier(position: string, scoringType: string): number {
  const scoring = scoringType.toLowerCase().replace('-', '_');
  if (position === 'WR' || position === 'TE') {
    if (scoring === 'ppr') return 1.15;
    if (scoring === 'half_ppr' || scoring === 'half') return 1.08;
  }
  if (position === 'RB' && scoring === 'standard') return 1.1;
  return 1.0;
}

function tePremiumFromRules(leagueRules?: LeagueRules | null): number {
  if (!leagueRules) return 0;
  const raw = leagueRules.scoring_settings?.raw_settings ?? {};
  for (const key of ['bonus_rec_te', 'rec_te']) {
    const value = Number((raw as Record<string, unknown>)[key]);
    if (Number.isFinite(value) && value > 0) {
      return value;
    }
  }
  const special = leagueRules.scoring_settings?.special_scoring ?? [];
  if (special.some((entry) => /te/i.test(entry) && /premium/i.test(entry))) {
    return 0.5;
  }
  return 0;
}

function formatMultiplier(position: string, leagueRules?: LeagueRules | null): number {
  if (!leagueRules) return 1;

  const pos = position.toUpperCase();
  const teamCount = leagueRules.team_count ?? 12;
  const qbStarters = leagueRules.roster_settings?.positions?.QB ?? 0;
  const hasSuperflex = Boolean(leagueRules.ai_context?.superflex);
  const is2qb = !hasSuperflex && qbStarters >= 2;

  if (pos === 'QB') {
    if (hasSuperflex) return QB_PREMIUM_SUPERFLEX;
    if (is2qb) return QB_PREMIUM_2QB;
    return 1;
  }

  if (pos === 'TE') {
    const tePremium = tePremiumFromRules(leagueRules);
    let mult = 1;
    if (teamCount >= 12) {
      mult = tePremium > 0 ? TE_SCARCITY_LARGE_WITH_PREMIUM : TE_SCARCITY_LARGE_LEAGUE;
    }
    if (tePremium > 0) {
      mult += tePremium;
    }
    return mult;
  }

  return 1;
}

export function calculateDeterministicTradeValue(
  player: {
    id?: string | number;
    player_id?: string | number;
    name?: string;
    position?: string;
    age?: number;
    team?: string;
  },
  leagueRules?: LeagueRules | null
): number {
  const position = (player.position || 'UNKNOWN').toUpperCase();
  const age = player.age ?? 27;
  const team = player.team || '';
  const playerKey = String(
    player.id ?? player.player_id ?? player.name ?? 'unknown'
  );
  const scoringType =
    leagueRules?.scoring_type || leagueRules?.scoring_settings?.type || 'standard';

  const [min, max] = POSITION_RANGES[position] || [8, 15];
  const seed = `${playerKey}:${position}:${age}:${team}:${scoringType}`;
  const unit = stableUnit(seed);
  const baseValue = min + unit * (max - min);

  const value =
    baseValue *
    ageMultiplier(age) *
    teamMultiplier(team) *
    scoringMultiplier(position, scoringType) *
    formatMultiplier(position, leagueRules);

  return Math.round(value * 10) / 10;
}
