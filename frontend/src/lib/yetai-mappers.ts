import { formatSportName } from '@/lib/formatting';
import { parseOddsValue } from '@/lib/yetai-format';
import { hasRealMatchup, isPlaceholderMatchup } from '@/lib/yetai-matchup';
import type { ActivityBet, DesignPick } from '@/components/yetai/types';

function matchupFromApiBet(bet: {
  game?: string;
  home_team?: string;
  away_team?: string;
  sport?: string;
  bet_type?: string;
}): string {
  const away = bet.away_team?.trim();
  const home = bet.home_team?.trim();
  if (away && home) {
    if (/\s+vs\.?\s+/i.test(bet.game || '')) {
      return bet.game!;
    }
    return `${away} @ ${home}`;
  }
  const game = bet.game?.trim();
  if (game && /^vs\s+/i.test(game)) {
    return game;
  }
  if (game && hasRealMatchup(game)) {
    return game;
  }
  if ((bet.bet_type || '').toLowerCase() === 'prop' || (game && looksLikePropSelectionTitle(game))) {
    const sport = bet.sport ? formatSportName(bet.sport) : '';
    return sport ? `${sport} player prop` : 'Player prop';
  }
  if (game && !isPlaceholderMatchup(game)) {
    return game;
  }
  return 'TBD';
}

/** Auto-pick used to store the bet line in ``title``; don't treat that as a matchup. */
function looksLikePropSelectionTitle(game: string): boolean {
  return /\b(under|over)\b/i.test(game) && /\d/.test(game);
}

export function apiBetToDesignPick(bet: {
  id: string;
  sport?: string;
  game?: string;
  home_team?: string;
  away_team?: string;
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
    matchup: matchupFromApiBet(bet),
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
