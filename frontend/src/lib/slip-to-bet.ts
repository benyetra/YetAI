import { oddsUtils } from '@/lib/api';
import type { SlipItem } from '@/components/yetai/types';

export type SlipBetType = 'moneyline' | 'spread' | 'total';

export interface SlipBetLeg {
  game_id: string;
  bet_type: SlipBetType;
  selection: string;
  odds: number;
  home_team: string;
  away_team: string;
  sport: string;
  commence_time: string;
}

export function slipKeyToBetType(key: string): SlipBetType {
  if (key.startsWith('ml')) return 'moneyline';
  if (key.startsWith('spread')) return 'spread';
  return 'total';
}

/** Build API selection string from slip key + raw odds game. */
export function slipItemToSelection(item: SlipItem): string {
  const game = item.rawGame as {
    home_team?: string;
    away_team?: string;
  } | undefined;

  if (!game?.home_team || !game?.away_team) {
    return item.label;
  }

  const extracted = oddsUtils.extractSimpleOdds(item.rawGame);
  const { home_team: home, away_team: away } = game;

  switch (item.key) {
    case 'ml-away':
      return away;
    case 'ml-home':
      return home;
    case 'spread-away': {
      const line = extracted.away_spread ?? -(extracted.spread ?? 0);
      return `${away} ${line > 0 ? '+' : ''}${line}`;
    }
    case 'spread-home': {
      const line = extracted.home_spread ?? extracted.spread ?? 0;
      return `${home} ${line > 0 ? '+' : ''}${line}`;
    }
    case 'total-over':
      return `Over ${extracted.total}`;
    case 'total-under':
      return `Under ${extracted.total}`;
    default:
      return item.label;
  }
}

export function slipItemToLeg(item: SlipItem): SlipBetLeg | null {
  const game = item.rawGame as {
    id?: string;
    home_team?: string;
    away_team?: string;
    sport_key?: string;
    sport?: string;
    commence_time?: string;
  } | undefined;

  if (!game?.home_team || !game?.away_team || !game.commence_time) {
    return null;
  }

  return {
    game_id: item.gameId || game.id || '',
    bet_type: slipKeyToBetType(item.key),
    selection: slipItemToSelection(item),
    odds: item.odds,
    home_team: game.home_team,
    away_team: game.away_team,
    sport: game.sport_key || game.sport || 'unknown',
    commence_time: game.commence_time,
  };
}

export function slipItemsToLegs(slip: SlipItem[]): { legs: SlipBetLeg[]; missing: SlipItem[] } {
  const legs: SlipBetLeg[] = [];
  const missing: SlipItem[] = [];
  for (const item of slip) {
    const leg = slipItemToLeg(item);
    if (leg) legs.push(leg);
    else missing.push(item);
  }
  return { legs, missing };
}

export function parlayAmericanOdds(slip: SlipItem[]): number {
  const decimal = slip.reduce((acc, b) => {
    const o = b.odds;
    const d = o > 0 ? 1 + o / 100 : 1 + 100 / Math.abs(o);
    return acc * d;
  }, 1);
  if (decimal >= 2) return Math.round((decimal - 1) * 100);
  return Math.round(-100 / (decimal - 1));
}
