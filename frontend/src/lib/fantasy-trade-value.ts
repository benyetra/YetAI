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
    scoringMultiplier(position, scoringType);

  return Math.round(value * 10) / 10;
}
