import { formatSportName, formatLocalTime } from '@/lib/formatting';
import { oddsUtils } from '@/lib/api';
import { teamAbbr } from '@/lib/yetai-format';
import type { DesignGame } from '@/components/yetai/types';

export function apiGameToDesignGame(game: {
  id: string;
  sport_key?: string;
  sport_title?: string;
  commence_time: string;
  home_team: string;
  away_team: string;
  bookmakers?: unknown[];
}): DesignGame {
  const extracted = oddsUtils.extractSimpleOdds(game);
  const league = formatSportName(game.sport_key || game.sport_title || 'SPORT');
  const homeAbbr = teamAbbr(game.home_team);
  const awayAbbr = teamAbbr(game.away_team);
  const homeSpread = extracted.home_spread ?? extracted.spread ?? 0;
  const awaySpread =
    extracted.away_spread ??
    (typeof homeSpread === 'number' ? -homeSpread : 0);

  return {
    id: game.id,
    league,
    tag: formatLocalTime(game.commence_time),
    time: formatLocalTime(game.commence_time),
    home: { abbr: homeAbbr, name: game.home_team, rec: '' },
    away: { abbr: awayAbbr, name: game.away_team, rec: '' },
    ml: {
      home: extracted.home_odds ?? -110,
      away: extracted.away_odds ?? -110,
    },
    spread: {
      home: homeSpread,
      homeOdds: -110,
      away: awaySpread,
      awayOdds: -110,
    },
    total: {
      line: extracted.total || 0,
      over: -110,
      under: -110,
    },
    sport_key: game.sport_key,
    raw: game,
  };
}

export function spreadLabel(abbr: string, line: number | string): string {
  if (typeof line === 'string') return `${abbr} ${line}`;
  const prefix = line > 0 ? '+' : '';
  return `${abbr} ${prefix}${line}`;
}

export function liveMarketToDesignGame(market: {
  game_id: string;
  sport: string;
  home_team: string;
  away_team: string;
  time_remaining?: string | null;
  home_score?: number;
  away_score?: number;
  moneyline_home?: number | null;
  moneyline_away?: number | null;
  spread_line?: number | null;
  spread_home_odds?: number | null;
  spread_away_odds?: number | null;
  total_line?: number | null;
  total_over_odds?: number | null;
  total_under_odds?: number | null;
}): DesignGame {
  const league = formatSportName(market.sport);
  const homeAbbr = teamAbbr(market.home_team);
  const awayAbbr = teamAbbr(market.away_team);
  const spreadHome = market.spread_line ?? 0;

  return {
    id: market.game_id,
    league,
    tag: market.time_remaining || 'Live',
    time: market.time_remaining || 'Live',
    home: { abbr: homeAbbr, name: market.home_team, score: market.home_score ?? 0 },
    away: { abbr: awayAbbr, name: market.away_team, score: market.away_score ?? 0 },
    ml: {
      home: market.moneyline_home ?? -110,
      away: market.moneyline_away ?? -110,
    },
    spread: {
      home: spreadHome,
      homeOdds: market.spread_home_odds ?? -110,
      away: typeof spreadHome === 'number' ? -spreadHome : 0,
      awayOdds: market.spread_away_odds ?? -110,
    },
    total: {
      line: market.total_line ?? 0,
      over: market.total_over_odds ?? -110,
      under: market.total_under_odds ?? -110,
    },
    sport_key: market.sport,
  };
}
