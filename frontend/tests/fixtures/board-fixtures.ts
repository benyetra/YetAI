/** Realistic /api/v1/predictions/{sport} payloads in three states, built from the backend's shapes
 *  (backend/app/api/v1/predictions.py `_withhold_board_picks`). */
type Row = Record<string, unknown>;
export type BoardSport = 'nba' | 'nfl' | 'nhl';
export type BoardState = 'withheld' | 'open' | 'empty';

const WITHHELD_REASON = 'unproven_record';
// Every field the backend nulls on a withheld row (projections and lines stay).
const PICK_FIELDS = [
  'recommendation', 'betting_recommendation', 'bet_size', 'fanduel_over_under', 'fanduel_price',
  'value_tier', 'edge_category', 'pick_confidence', 'confidence', 'confidence_score',
  'edge', 'edge_saves', 'edge_percentage', 'best_book', 'best_line', 'best_price',
];

function withhold(row: Row): Row {
  const out: Row = { ...row };
  for (const f of PICK_FIELDS) if (f in out || f === 'recommendation' || f === 'edge') out[f] = null;
  out.pick_withheld = WITHHELD_REASON;
  return out;
}

const game = (id: number, away: string, home: string, time: string) => ({
  id, away_team_name: away, home_team_name: home, game_time: time,
});

function nbaProp(id: number, name: string, team: string, opp: string, projKey: string, proj: number, line: number): Row {
  const edge = Math.round((proj - line) * 10) / 10;
  return {
    id, player_name: name, team_name: team, opponent_team_name: opp, [projKey]: proj,
    fanduel_line: line, edge, recommendation: edge >= 0 ? 'OVER' : 'UNDER',
    fanduel_over_under: edge >= 0 ? 'over' : 'under', pick_confidence: 71, confidence_score: 71,
    value_tier: Math.abs(edge) >= 2 ? 'strong' : Math.abs(edge) >= 1 ? 'lean' : null, news: '',
  };
}

const open = (rows: Row[]) => rows;
const shut = (rows: Row[]) => rows.map(withhold);

function nba(state: BoardState): Row {
  const g1 = game(1, 'Boston Celtics', 'Miami Heat', '2026-11-18T19:30:00-05:00');
  const g2 = game(2, 'Denver Nuggets', 'Los Angeles Lakers', '2026-11-18T22:00:00-05:00');
  const spread = (g: Row, margin: number): Row => ({
    ...g, home_win_prob: 0.58, projected_margin: margin, market_spread_home: -3.5,
    edge: 2.1, recommendation: 'HOME', pick_confidence: 66,
  });
  const total = (g: Row, t: number): Row => ({
    ...g, projected_total: t, home_projected_score: t / 2 + 2, away_projected_score: t / 2 - 2,
    market_total: 224.5, edge: t - 224.5, recommendation: t > 224.5 ? 'OVER' : 'UNDER', pick_confidence: 62,
  });
  const assists = [
    nbaProp(11, 'Tyrese Haliburton', 'Indiana Pacers', 'Chicago Bulls', 'projected_assists', 11.2, 9.5),
    nbaProp(12, 'Nikola Jokic', 'Denver Nuggets', 'Los Angeles Lakers', 'projected_assists', 9.4, 9.5),
  ];
  const points = [
    nbaProp(21, 'Jayson Tatum', 'Boston Celtics', 'Miami Heat', 'projected_points', 28.4, 26.5),
    nbaProp(22, 'LeBron James', 'Los Angeles Lakers', 'Denver Nuggets', 'projected_points', 24.1, 24.5),
  ];
  const rebounds = [nbaProp(31, 'Bam Adebayo', 'Miami Heat', 'Boston Celtics', 'projected_rebounds', 10.8, 9.5)];
  const threes = [nbaProp(41, 'Stephen Curry', 'Golden State Warriors', 'Utah Jazz', 'projected_three_pt_made', 4.6, 4.5)];
  const steals = [nbaProp(51, 'Jrue Holiday', 'Boston Celtics', 'Miami Heat', 'projected_steals', 1.5, 1.5)];
  const blocks = [nbaProp(61, 'Victor Wembanyama', 'San Antonio Spurs', 'Houston Rockets', 'projected_blocks', 3.6, 3.5)];
  const pra = [nbaProp(71, 'Luka Doncic', 'Dallas Mavericks', 'Phoenix Suns', 'projected_pra', 49.2, 47.5)];
  if (state === 'empty') {
    return Object.fromEntries(
      ['spreads', 'totals', 'points', 'assists', 'rebounds', 'three_point', 'steals', 'blocks', 'pra'].map((k) => [k, []]),
    );
  }
  const live = state === 'open';
  return {
    spreads: shut([spread(g1, 4.2), spread(g2, -1.5)]),
    totals: shut([total(g1, 221.8), total(g2, 229.4)]),
    points: shut(points), assists: live ? open(assists) : shut(assists), rebounds: shut(rebounds),
    three_point: shut(threes), steals: shut(steals), blocks: shut(blocks), pra: shut(pra),
  };
}

function nfl(state: BoardState): Row {
  const g1 = game(1, 'Kansas City Chiefs', 'Buffalo Bills', '2026-11-22T16:25:00-05:00');
  const g2 = game(2, 'Detroit Lions', 'Green Bay Packers', '2026-11-22T13:00:00-05:00');
  const spread = (g: Row): Row => ({
    ...g, home_win_prob: 0.55, projected_margin: 2.8, market_spread_home: -2.5,
    edge: 3.4, recommendation: 'HOME', pick_confidence: 64,
  });
  const total = (g: Row): Row => ({
    ...g, projected_total: 49.6, home_projected_score: 25.1, away_projected_score: 24.5,
    market_total: 47.5, edge: 2.1, recommendation: 'OVER', pick_confidence: 60,
  });
  const qb = (id: number, name: string, team: string, opp: string, y: number, line: number): Row => ({
    id, qb_player_name: name, team_name: team, opponent_team_name: opp, predicted_passing_yards: y,
    ou_line: line, edge: y - line, recommendation: y >= line ? 'OVER' : 'UNDER', pick_confidence: 68,
    value_tier: 'lean', news: '',
  });
  const recv = (id: number, name: string, pos: string, team: string, opp: string, y: number, line: number): Row => ({
    id, player_name: name, position: pos, team_name: team, opponent_team_name: opp,
    predicted_receiving_yards: y, ou_line: line, edge: y - line, recommendation: y >= line ? 'OVER' : 'UNDER',
    pick_confidence: 73, value_tier: Math.abs(y - line) >= 8 ? 'strong' : 'lean', news: '',
  });
  const td = (id: number, name: string, pos: string, team: string, opp: string, p: number, odds: number): Row => ({
    id, player_name: name, position: pos, team_name: team, opponent_team_name: opp, td_probability: p,
    market_odds: odds, edge: 0.06, recommendation: 'OVER', betting_recommendation: 'OVER', confidence_score: 64,
  });
  const kicker = (id: number, name: string, team: string, opp: string): Row => ({
    id, kicker_player_name: name, team_name: team, opponent_team_name: opp,
    predicted_fg_attempts: 2.1, predicted_fg_made: 1.8, predicted_success_rate: 85.7, model_confidence: 55,
  });
  if (state === 'empty') {
    return Object.fromEntries(
      ['spreads', 'totals', 'qb_predictions', 'receiving_yards_predictions', 'anytime_td_predictions', 'kicker_predictions'].map(
        (k) => [k, []],
      ),
    );
  }
  const recvRows = [
    recv(31, "Ja'Marr Chase", 'WR', 'Cincinnati Bengals', 'Pittsburgh Steelers', 94.5, 82.5),
    recv(32, 'Travis Kelce', 'TE', 'Kansas City Chiefs', 'Buffalo Bills', 61.2, 58.5),
  ];
  return {
    spreads: shut([spread(g1), spread(g2)]),
    totals: shut([total(g1), total(g2)]),
    qb_predictions: shut([
      qb(11, 'Josh Allen', 'Buffalo Bills', 'Kansas City Chiefs', 268.4, 255.5),
      qb(12, 'Jared Goff', 'Detroit Lions', 'Green Bay Packers', 247.9, 252.5),
    ]),
    receiving_yards_predictions: state === 'open' ? open(recvRows) : shut(recvRows),
    anytime_td_predictions: shut([
      td(41, 'Josh Allen', 'QB', 'Buffalo Bills', 'Kansas City Chiefs', 0.41, 135),
      td(42, 'Amon-Ra St. Brown', 'WR', 'Detroit Lions', 'Green Bay Packers', 0.52, -110),
    ]),
    kicker_predictions: [
      { ...kicker(51, 'Tyler Bass', 'Buffalo Bills', 'Kansas City Chiefs'), model_confidence: null },
      { ...kicker(52, 'Jake Bates', 'Detroit Lions', 'Green Bay Packers'), model_confidence: null },
    ],
  };
}

function nhl(state: BoardState): Row {
  const teamTotal = (id: number, away: string, home: string): Row => ({
    id, away_team_name: away, home_team_name: home, game_time_et: '2026-11-18T19:00:00-05:00',
    predicted_home_goals: 3.2, predicted_away_goals: 2.9, predicted_total_goals: 6.1, draftkings_ou_line: 5.5,
    betting_recommendation: 'OVER', recommendation: 'OVER', edge: 0.6, confidence: 63,
  });
  const goalie = (id: number, name: string, team: string, opp: string): Row => ({
    id, goalie_name: name, team_name: team, opponent_team_name: opp, predicted_saves: 29.4, saves_line: 27.5,
    edge: 1.9, edge_saves: 1.9, recommendation: 'OVER', betting_recommendation: 'OVER 27.5',
    confidence: 69, value_tier: 'strong', news: '',
  });
  const shots = (id: number, name: string, team: string, opp: string): Row => ({
    id, player_name: name, team_name: team, opponent_team_name: opp, predicted_shots: 3.9, shots_line: 3.5,
    edge: 0.4, recommendation: 'OVER', betting_recommendation: 'OVER 3.5', confidence: 58, value_tier: 'lean', news: '',
  });
  if (state === 'empty') return { team_totals: [], goalie_predictions: [], player_shots: [] };
  const goalies = [
    goalie(11, 'Igor Shesterkin', 'New York Rangers', 'Boston Bruins'),
    goalie(12, 'Connor Hellebuyck', 'Winnipeg Jets', 'Colorado Avalanche'),
  ];
  return {
    team_totals: shut([teamTotal(1, 'Boston Bruins', 'New York Rangers'), teamTotal(2, 'Colorado Avalanche', 'Winnipeg Jets')]),
    goalie_predictions: state === 'open' ? open(goalies) : shut(goalies),
    player_shots: shut([shots(21, 'Auston Matthews', 'Toronto Maple Leafs', 'Montreal Canadiens'), shots(22, 'Nathan MacKinnon', 'Colorado Avalanche', 'Winnipeg Jets')]),
  };
}

export function boardPayload(sport: BoardSport, state: BoardState): Row {
  return { nba, nfl, nhl }[sport](state);
}
