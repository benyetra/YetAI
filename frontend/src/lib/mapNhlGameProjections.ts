/** Map NHL team totals API rows into unified game projection cards. */

type Row = Record<string, unknown>;

function num(v: unknown): number | null {
  const n = typeof v === 'number' ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}

function deriveValueRating(totalRec: string, edge: number | null): string {
  const absEdge = Math.abs(edge ?? 0);
  const hasTotal = totalRec === 'OVER' || totalRec === 'UNDER';
  if (hasTotal && absEdge >= 0.5) return 'Strong';
  if (hasTotal && absEdge >= 0.25) return 'Lean';
  return 'No Edge';
}

function winProbFromGoals(homeGoals: number, awayGoals: number): number {
  const sum = homeGoals + awayGoals;
  if (sum <= 0) return 0.5;
  return homeGoals / sum;
}

export function mapNhlTeamTotalsRows(totals: Row[]): Row[] {
  return totals.map((total) => {
    const home = String(total.home_team_name ?? '');
    const away = String(total.away_team_name ?? '');
    const homeGoals = num(total.predicted_home_goals) ?? 0;
    const awayGoals = num(total.predicted_away_goals) ?? 0;
    const homeWp = winProbFromGoals(homeGoals, awayGoals);
    const totalRec = String(total.betting_recommendation ?? 'NO_PLAY').toUpperCase();
    const edge = num(total.edge);
    const marketLine = num(total.draftkings_ou_line) ?? num(total.suggested_ou_line);

    return {
      id: total.id,
      game_id: total.id,
      home_team: home,
      away_team: away,
      home_win_prob: homeWp,
      away_win_prob: 1 - homeWp,
      away_projected_runs: awayGoals,
      home_projected_runs: homeGoals,
      projected_total: num(total.predicted_total_goals),
      market_total: marketLine,
      edge_vs_market_total: edge,
      total_recommendation:
        totalRec === 'OVER' || totalRec === 'UNDER' ? totalRec : 'NO_PLAY',
      model_confidence: num(total.confidence),
      value_rating: deriveValueRating(totalRec, edge),
      away_pitcher_name: '',
      home_pitcher_name: '',
      actual_home_score: total.actual_home_score,
      actual_away_score: total.actual_away_score,
      actual_total_runs: total.actual_total_goals,
      total_correct: total.recommendation_correct,
    };
  });
}
