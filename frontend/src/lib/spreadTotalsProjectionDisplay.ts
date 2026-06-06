/** Align spread-model margin/win prob with totals-based score display (NBA/WNBA/NFL). */

import type { GameProjectionsVariant } from '@/lib/gameProjectionsTypes';

type Row = Record<string, unknown>;

const SPREAD_SCORE_VARIANTS = new Set<GameProjectionsVariant>(['nba', 'wnba', 'nfl']);

function num(v: unknown): number | null {
  const n = typeof v === 'number' ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}

export function spreadHomeMargin(proj: Row): number | null {
  return num(proj.run_line) ?? num(proj.projected_margin);
}

export function projectedTotal(proj: Row): number | null {
  const total = num(proj.projected_total);
  if (total != null) return total;
  const away = num(proj.away_projected_runs);
  const home = num(proj.home_projected_runs);
  if (away != null && home != null) return away + home;
  return null;
}

export function scoresFromSpreadAndTotal(
  projectedTotal: number,
  homeMargin: number,
): { home: number; away: number } {
  return {
    home: (projectedTotal + homeMargin) / 2,
    away: (projectedTotal - homeMargin) / 2,
  };
}

export function totalsScoreMargin(proj: Row): number | null {
  const away = num(proj.away_projected_runs);
  const home = num(proj.home_projected_runs);
  if (away == null || home == null) return null;
  return Math.abs(home - away);
}

export type DisplayTeamScores = {
  home: number | null;
  away: number | null;
  alignedWithSpread: boolean;
};

export function displayTeamScores(
  proj: Row,
  variant: GameProjectionsVariant,
): DisplayTeamScores {
  const awayRaw = num(proj.away_projected_runs);
  const homeRaw = num(proj.home_projected_runs);

  if (!SPREAD_SCORE_VARIANTS.has(variant)) {
    return { home: homeRaw, away: awayRaw, alignedWithSpread: false };
  }

  const margin = spreadHomeMargin(proj);
  const total = projectedTotal(proj);
  if (margin == null || total == null) {
    return { home: homeRaw, away: awayRaw, alignedWithSpread: false };
  }

  const aligned = scoresFromSpreadAndTotal(total, margin);
  return {
    home: aligned.home,
    away: aligned.away,
    alignedWithSpread: true,
  };
}

export type DisplaySpreadMargin = {
  marginAbs: number | null;
  favAbbr: string | null;
  homeAbbr: string;
  awayAbbr: string;
  spreadHomeMargin: number | null;
  totalsMargin: number | null;
};

export function displaySpreadMargin(
  proj: Row,
  variant: GameProjectionsVariant,
  homeAbbr: string,
  awayAbbr: string,
): DisplaySpreadMargin {
  const spreadMargin = SPREAD_SCORE_VARIANTS.has(variant) ? spreadHomeMargin(proj) : null;
  const totalsMargin = totalsScoreMargin(proj);

  if (spreadMargin != null) {
    const favAbbr = spreadMargin >= 0 ? homeAbbr : awayAbbr;
    return {
      marginAbs: Math.abs(spreadMargin),
      favAbbr,
      homeAbbr,
      awayAbbr,
      spreadHomeMargin: spreadMargin,
      totalsMargin,
    };
  }

  const away = num(proj.away_projected_runs);
  const home = num(proj.home_projected_runs);
  if (away != null && home != null) {
    const homeFav = home >= away;
    return {
      marginAbs: Math.abs(home - away),
      favAbbr: homeFav ? homeAbbr : awayAbbr,
      homeAbbr,
      awayAbbr,
      spreadHomeMargin: null,
      totalsMargin,
    };
  }

  const homeWp = num(proj.home_win_prob) ?? 0.5;
  const awayWp = num(proj.away_win_prob) ?? 1 - homeWp;
  const homeFav = homeWp >= awayWp;
  const favProb = homeFav ? homeWp : awayWp;
  return {
    marginAbs: Math.abs((favProb - 0.5) * 10),
    favAbbr: homeFav ? homeAbbr : awayAbbr,
    homeAbbr,
    awayAbbr,
    spreadHomeMargin: null,
    totalsMargin,
  };
}

export function spreadMarketEdge(proj: Row): number | null {
  const edge = num(proj.spread_edge);
  if (edge != null) return edge;
  const margin = spreadHomeMargin(proj);
  const marketSpread = num(proj.market_spread);
  if (margin == null || marketSpread == null) return null;
  return margin - -marketSpread;
}
