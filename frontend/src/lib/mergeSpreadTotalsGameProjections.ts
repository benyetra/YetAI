/** Merge spread + totals API rows into unified game projection cards (NBA, WNBA). */

type Row = Record<string, unknown>;

function gameKey(row: Row): string {
  const home = String(row.home_team_name ?? row.home_team ?? '')
    .trim()
    .toLowerCase();
  const away = String(row.away_team_name ?? row.away_team ?? '')
    .trim()
    .toLowerCase();
  return `${away}|${home}`;
}

function num(v: unknown): number | null {
  const n = typeof v === 'number' ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}

function deriveValueRating(
  spreadRec: string | null,
  totalRec: string | null,
  spreadEdge: number | null,
  totalEdge: number | null,
): string {
  const spreadAbs = Math.abs(spreadEdge ?? 0);
  const totalAbs = Math.abs(totalEdge ?? 0);
  const hasSpread = spreadRec === 'HOME' || spreadRec === 'AWAY';
  const hasTotal = totalRec === 'OVER' || totalRec === 'UNDER';
  if ((hasSpread && spreadAbs >= 4) || (hasTotal && totalAbs >= 4)) return 'Strong';
  if ((hasSpread && spreadAbs >= 2) || (hasTotal && totalAbs >= 2)) return 'Lean';
  return 'No Edge';
}

function formatStarters(starters: unknown): string | undefined {
  if (!Array.isArray(starters) || !starters.length) return undefined;
  const names = starters
    .map((s) => {
      if (typeof s === 'string') return s;
      if (s && typeof s === 'object' && 'name' in s) return String((s as { name: unknown }).name);
      return null;
    })
    .filter(Boolean) as string[];
  return names.length ? names.join(', ') : undefined;
}

function mergeRow(spread?: Row, total?: Row): Row {
  const home = String(spread?.home_team_name ?? total?.home_team_name ?? '');
  const away = String(spread?.away_team_name ?? total?.away_team_name ?? '');
  const homeWp = num(spread?.home_win_prob) ?? 0.5;
  const spreadRec = String(spread?.recommendation ?? 'NO_PLAY').toUpperCase();
  const totalRec = String(total?.recommendation ?? 'NO_PLAY').toUpperCase();
  const spreadEdge = num(spread?.edge);
  const totalEdge = num(total?.edge);
  const spreadSide =
    spreadRec === 'HOME' || spreadRec === 'AWAY' ? spreadRec : null;

  return {
    id: spread?.id ?? total?.id,
    game_id: spread?.id ?? total?.id,
    home_team: home,
    away_team: away,
    home_win_prob: homeWp,
    away_win_prob: 1 - homeWp,
    projected_margin: spread?.projected_margin,
    run_line: spread?.projected_margin,
    market_spread: spread?.market_spread_home,
    spread_recommendation: spreadSide,
    projected_total: total?.projected_total,
    home_projected_runs: total?.home_projected_score,
    away_projected_runs: total?.away_projected_score,
    market_total: total?.market_total,
    edge_vs_market_total: totalEdge,
    total_recommendation:
      totalRec === 'OVER' || totalRec === 'UNDER' ? totalRec : 'NO_PLAY',
    model_confidence: num(spread?.confidence_score) ?? num(total?.confidence_score),
    value_rating: deriveValueRating(spreadSide, totalRec, spreadEdge, totalEdge),
    away_pitcher_name: formatStarters(total?.away_starters) ?? '',
    home_pitcher_name: formatStarters(total?.home_starters) ?? '',
    actual_home_score: total?.actual_home_score ?? spread?.actual_home_score,
    actual_away_score: total?.actual_away_score ?? spread?.actual_away_score,
    actual_total_runs: total?.actual_total_runs ?? total?.actual_total,
    actual_winner: spread?.actual_winner ?? total?.actual_winner,
    spread_correct: spread?.spread_correct,
    total_correct: total?.total_correct,
    ml_correct: spread?.ml_correct,
  };
}

export function mergeSpreadTotalsGameProjections(spreads: Row[], totals: Row[]): Row[] {
  const totalsByKey = new Map(totals.map((t) => [gameKey(t), t]));
  const seen = new Set<string>();
  const rows: Row[] = [];

  for (const spread of spreads) {
    const key = gameKey(spread);
    seen.add(key);
    rows.push(mergeRow(spread, totalsByKey.get(key)));
  }

  for (const total of totals) {
    const key = gameKey(total);
    if (!seen.has(key)) {
      rows.push(mergeRow(undefined, total));
    }
  }

  return rows;
}
