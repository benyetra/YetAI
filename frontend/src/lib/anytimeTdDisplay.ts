import {
  formatString,
  type ColumnDef,
} from '@/components/PredictionsTable';
import { formatOdds } from '@/lib/formatting';
import {
  formatOpponentTeamCell,
  formatPickConfidence,
  formatSignedEdge,
  formatTeamCell,
  OPPONENT_TEAM_COLUMN,
  TEAM_COLUMN,
} from '@/lib/propProjectionDisplay';

const TRUTHY_ENV = new Set(['1', 'true', 'yes']);

/** Client gate for NFL anytime TD board (`NEXT_PUBLIC_NFL_ANYTIME_TD_UI`). */
export function isAnytimeTdUiEnabled(
  envValue: string | undefined = process.env.NEXT_PUBLIC_NFL_ANYTIME_TD_UI,
): boolean {
  if (envValue === undefined || envValue === '') return false;
  return TRUTHY_ENV.has(envValue.trim().toLowerCase());
}

/** Model P(anytime TD) as whole-percent display (0–1 or 0–100 inputs). */
export function formatTdProbability(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (Number.isNaN(n)) return formatString(value);
  const pct = n <= 1 ? Math.round(n * 100) : Math.round(n);
  return `${pct}%`;
}

export function formatMarketOdds(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (Number.isNaN(n)) return formatString(value);
  return formatOdds(n);
}

const OPPONENT_COLUMN: ColumnDef = {
  ...OPPONENT_TEAM_COLUMN,
  label: 'Opp',
};

/** Anytime TD prop board — model anytime scorer (not first/last TD). */
export const ANYTIME_TD_COLUMNS: ColumnDef[] = [
  { key: 'player_name', label: 'Player', format: (v) => formatString(v) },
  { key: 'position', label: 'Pos', format: (v) => formatString(v) },
  {
    ...TEAM_COLUMN,
    format: (v, row) => formatTeamCell(v, row),
  },
  {
    ...OPPONENT_COLUMN,
    format: (v, row) => formatOpponentTeamCell(v, row),
  },
  {
    key: 'td_probability',
    label: 'P(TD)',
    align: 'right',
    mono: true,
    format: (v) => formatTdProbability(v),
  },
  {
    key: 'market_odds',
    label: 'Odds',
    align: 'right',
    mono: true,
    format: (v) => formatMarketOdds(v),
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
    key: 'confidence_score',
    label: 'Conf',
    align: 'right',
    mono: true,
    format: (v, row) =>
      formatPickConfidence(v ?? row.confidence ?? row.pick_confidence),
    className: 'prop-conf-cell',
  },
];
