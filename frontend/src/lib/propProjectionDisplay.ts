import {
  formatNumber,
  formatString,
  type ColumnDef,
} from '@/components/PredictionsTable';

export type PropValueTier = 'strong' | 'lean';

export function formatSignedEdge(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (Number.isNaN(n)) return formatString(value);
  const sign = n > 0 ? '+' : '';
  return `${sign}${n.toFixed(1)}`;
}

export function formatPickConfidence(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (Number.isNaN(n)) return formatString(value);
  const pct = n <= 1 ? Math.round(n * 100) : Math.round(n);
  return `${pct}%`;
}

export function propValueTier(row: Record<string, unknown>): PropValueTier | null {
  const tier = row.value_tier;
  if (tier === 'strong' || tier === 'lean') return tier;
  return null;
}

export function propRowClassName(row: Record<string, unknown>): string | undefined {
  const tier = propValueTier(row);
  if (tier === 'strong') return 'is-strong-play';
  if (tier === 'lean') return 'is-value-play';
  return undefined;
}

/** Highlighted prop row (strong or lean edge) — matches YetAI Hits criteria. */
export function isTopPlay(row: Record<string, unknown>): boolean {
  return propValueTier(row) !== null;
}

export function countTopPlays(rows: Array<Record<string, unknown>>): number {
  return rows.filter(isTopPlay).length;
}

type BasketballPropColumnOptions = {
  projectedKey: string;
  projectedLabel: string;
  lineKey?: string;
  lineLabel?: string;
  edgeKey?: string;
  pickKey?: string;
  confidenceKey?: string;
};

export function formatNewsString(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  return formatString(value);
}

export function newsImpactClassName(value: unknown): string | undefined {
  const text = String(value ?? '');
  if (text.includes('[unknown]')) return 'news-impact-unknown';
  if (text.includes('↑') || text.includes('\u2191')) return 'news-impact-up';
  if (text.includes('↓') || text.includes('\u2193')) return 'news-impact-down';
  if (text.includes('[neutral]')) return 'news-impact-neutral';
  return undefined;
}

/** Resolve team across sports (team_name vs MLB `team`). */
export function formatTeamCell(
  value: unknown,
  row: Record<string, unknown>
): string {
  return formatString(value ?? row.team_name ?? row.team);
}

/** Resolve opponent across sports (opponent_team_name vs MLB `opponent`). */
export function formatOpponentTeamCell(
  value: unknown,
  row: Record<string, unknown>
): string {
  return formatString(
    value ?? row.opponent_team_name ?? row.opponent ?? row.opponent_name
  );
}

export const TEAM_COLUMN: ColumnDef = {
  key: 'team_name',
  label: 'Team',
  format: (v, row) => formatTeamCell(v, row),
};

export const OPPONENT_TEAM_COLUMN: ColumnDef = {
  key: 'opponent_team_name',
  label: 'Opponent Team',
  format: (v, row) => formatOpponentTeamCell(v, row),
};

const NEWS_COLUMN: ColumnDef = {
  key: 'news',
  label: 'News',
  format: (v) => formatNewsString(v),
  className: 'prop-news-cell',
  sortable: false,
};

export function buildBasketballPropColumns({
  projectedKey,
  projectedLabel,
  lineKey = 'fanduel_line',
  lineLabel = 'FD Line',
  edgeKey = 'edge',
  pickKey = 'recommendation',
  confidenceKey = 'pick_confidence',
}: BasketballPropColumnOptions): ColumnDef[] {
  return [
    { key: 'player_name', label: 'Player', format: (v) => formatString(v) },
    TEAM_COLUMN,
    OPPONENT_TEAM_COLUMN,
    {
      key: projectedKey,
      label: projectedLabel,
      align: 'right',
      mono: true,
      format: (v) => formatNumber(v, 1),
    },
    {
      key: lineKey,
      label: lineLabel,
      align: 'right',
      mono: true,
      format: (v) => formatNumber(v, 1),
    },
    {
      key: edgeKey,
      label: 'Edge',
      align: 'right',
      mono: true,
      format: (v) => formatSignedEdge(v),
      className: 'prop-edge-cell',
    },
    {
      key: pickKey,
      label: 'Pick',
      format: (v, row) => formatString(v ?? row.fanduel_over_under),
      className: 'prop-pick-cell',
    },
    {
      key: confidenceKey,
      label: 'Conf',
      align: 'right',
      mono: true,
      format: (v, row) =>
        formatPickConfidence(v ?? row.confidence_score ?? row.confidence),
      className: 'prop-conf-cell',
    },
    {
      key: 'news',
      label: 'News',
      format: (v) => formatNewsString(v),
      className: 'prop-news-cell',
      sortable: false,
    },
  ];
}

export const WNBA_PROP_COLUMNS = {
  points: buildBasketballPropColumns({
    projectedKey: 'projected_points',
    projectedLabel: 'Proj Pts',
    lineKey: 'market_line',
    lineLabel: 'Line',
    confidenceKey: 'confidence_score',
  }),
  assists: buildBasketballPropColumns({
    projectedKey: 'projected_assists',
    projectedLabel: 'Proj Ast',
    lineKey: 'market_line',
    lineLabel: 'Line',
    confidenceKey: 'confidence_score',
  }),
  rebounds: buildBasketballPropColumns({
    projectedKey: 'projected_rebounds',
    projectedLabel: 'Proj Reb',
    lineKey: 'market_line',
    lineLabel: 'Line',
    confidenceKey: 'confidence_score',
  }),
  three_point: buildBasketballPropColumns({
    projectedKey: 'projected_three_pt_made',
    projectedLabel: 'Proj 3PM',
    lineKey: 'market_line',
    lineLabel: 'Line',
    confidenceKey: 'confidence_score',
  }),
  pra: buildBasketballPropColumns({
    projectedKey: 'projected_pra',
    projectedLabel: 'Proj PRA',
    lineKey: 'market_line',
    lineLabel: 'Line',
    confidenceKey: 'confidence_score',
  }),
};

export const NHL_GOALIE_COLUMNS: ColumnDef[] = [
  { key: 'goalie_name', label: 'Goalie', format: (v) => formatString(v) },
  TEAM_COLUMN,
  OPPONENT_TEAM_COLUMN,
  {
    key: 'predicted_saves',
    label: 'Proj Saves',
    align: 'right',
    mono: true,
    format: (v) => formatNumber(v, 1),
  },
  {
    key: 'saves_line',
    label: 'Saves Line',
    align: 'right',
    mono: true,
    format: (v) => formatNumber(v, 1),
  },
  {
    key: 'edge',
    label: 'Edge',
    align: 'right',
    mono: true,
    format: (v, row) => formatSignedEdge(v ?? row.edge_saves),
    className: 'prop-edge-cell',
  },
  {
    key: 'recommendation',
    label: 'Pick',
    format: (v, row) => formatString(v ?? row.betting_recommendation),
    className: 'prop-pick-cell',
  },
  {
    key: 'confidence',
    label: 'Conf',
    align: 'right',
    mono: true,
    format: (v) => formatPickConfidence(v),
    className: 'prop-conf-cell',
  },
  NEWS_COLUMN,
];

export const NHL_SHOTS_COLUMNS: ColumnDef[] = [
  { key: 'player_name', label: 'Player', format: (v) => formatString(v) },
  TEAM_COLUMN,
  OPPONENT_TEAM_COLUMN,
  {
    key: 'predicted_shots',
    label: 'Proj SOG',
    align: 'right',
    mono: true,
    format: (v) => formatNumber(v, 1),
  },
  {
    key: 'shots_line',
    label: 'Line',
    align: 'right',
    mono: true,
    format: (v) => formatNumber(v, 1),
  },
  {
    key: 'edge',
    label: 'Edge',
    align: 'right',
    mono: true,
    format: (v) => formatSignedEdge(v),
    className: 'prop-edge-cell',
  },
  {
    key: 'recommendation',
    label: 'Pick',
    format: (v, row) => formatString(v ?? row.betting_recommendation),
    className: 'prop-pick-cell',
  },
  {
    key: 'confidence',
    label: 'Conf',
    align: 'right',
    mono: true,
    format: (v) => formatPickConfidence(v),
    className: 'prop-conf-cell',
  },
  NEWS_COLUMN,
];

export const MLB_STRIKEOUT_COLUMNS_BASE = [
  { key: 'pitcher_name', label: 'Pitcher', format: (v: unknown) => formatString(v) },
  TEAM_COLUMN,
  OPPONENT_TEAM_COLUMN,
  {
    key: 'projected_strikeouts',
    label: 'Proj K',
    align: 'right' as const,
    mono: true,
    format: (v: unknown) => formatNumber(v, 1),
  },
  {
    key: 'projected_innings_pitched',
    label: 'Proj IP',
    align: 'right' as const,
    mono: true,
    format: (v: unknown) => formatNumber(v, 1),
  },
  {
    key: 'fanduel_line',
    label: 'FD Line',
    align: 'right' as const,
    mono: true,
    format: (v: unknown) => formatNumber(v, 1),
  },
  {
    key: 'k_edge',
    label: 'K Edge',
    align: 'right' as const,
    mono: true,
    format: (v: unknown) => formatSignedEdge(v),
    className: 'prop-edge-cell',
  },
  {
    key: 'yetai_pick',
    label: 'YetAI Pick',
    format: (v: unknown, row: Record<string, unknown>) =>
      formatString(v ?? row.fanduel_over_under),
    className: 'prop-pick-cell',
  },
  {
    key: 'pick_confidence',
    label: 'Conf',
    align: 'right' as const,
    mono: true,
    format: (v: unknown) => formatPickConfidence(v),
    className: 'prop-conf-cell',
  },
  NEWS_COLUMN,
];

export const NFL_QB_COLUMNS: ColumnDef[] = [
  { key: 'qb_player_name', label: 'QB', format: (v) => formatString(v) },
  TEAM_COLUMN,
  OPPONENT_TEAM_COLUMN,
  {
    key: 'predicted_passing_yards',
    label: 'Pass Yds',
    align: 'right',
    mono: true,
    format: (v) => formatNumber(v, 0),
  },
  {
    key: 'ou_line',
    label: 'O/U Line',
    align: 'right',
    mono: true,
    format: (v) => formatNumber(v, 1),
  },
  {
    key: 'edge',
    label: 'Edge',
    align: 'right',
    mono: true,
    format: (v) => formatSignedEdge(v),
    className: 'prop-edge-cell',
  },
  {
    key: 'recommendation',
    label: 'Pick',
    format: (v, row) => formatString(v ?? row.betting_recommendation),
    className: 'prop-pick-cell',
  },
  {
    key: 'pick_confidence',
    label: 'Conf',
    align: 'right',
    mono: true,
    format: (v, row) => formatPickConfidence(v ?? row.confidence_score),
    className: 'prop-conf-cell',
  },
  NEWS_COLUMN,
];
