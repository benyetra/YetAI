import { formatSportName } from '@/lib/formatting';
import { parseOddsValue } from '@/lib/yetai-format';
import type { ActivityBet, DesignPick } from '@/components/yetai/types';

export function apiBetToDesignPick(bet: {
  id: string;
  sport?: string;
  game?: string;
  bet_type?: string;
  pick: string;
  odds: string | number;
  confidence: number;
  reasoning?: string;
  game_time?: string;
  status?: string;
  is_premium?: boolean;
}): DesignPick {
  const league = formatSportName(bet.sport || 'NBA').slice(0, 4).toUpperCase();
  return {
    id: bet.id,
    league: bet.sport ? formatSportName(bet.sport) : league,
    matchup: bet.game || 'TBD',
    pick: bet.pick,
    odds: bet.odds,
    confidence: bet.confidence > 1 ? bet.confidence / 100 : bet.confidence,
    units: 1,
    reasoning: bet.reasoning,
    game_time: bet.game_time,
    sport: bet.sport,
    bet_type: bet.bet_type,
    status: bet.status,
    is_premium: bet.is_premium,
  };
}

export function apiHistoryToActivity(bet: {
  id: string;
  pick?: string;
  selection?: string;
  odds?: string | number;
  matchup?: string;
  game?: string;
  created_at?: string;
  placed_at?: string;
  source?: string;
  status?: string;
  stake?: number;
  potential_win?: number;
  payout?: number;
}): ActivityBet {
  const statusRaw = (bet.status || 'pending').toLowerCase();
  const status =
    statusRaw === 'won' || statusRaw === 'lost' || statusRaw === 'pushed'
      ? statusRaw
      : 'pending';

  return {
    id: bet.id,
    pick: bet.pick || bet.selection || 'Bet',
    odds: bet.odds ?? -110,
    matchup: bet.matchup || bet.game || '',
    date: bet.created_at || bet.placed_at || '',
    source: bet.source || 'YetAI',
    status,
    stake: bet.stake,
    payout: bet.payout ?? bet.potential_win,
  };
}

export function normalizeConfidence(confidence: number): number {
  if (confidence > 1) return confidence / 100;
  return confidence;
}

export function pickOddsNumber(odds: string | number): number {
  return parseOddsValue(odds);
}
