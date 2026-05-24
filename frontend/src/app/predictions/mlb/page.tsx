'use client';

import AccuracySummary from '@/components/yetai/AccuracySummary';
import MlbGameProjectionsGrid from '@/components/yetai/MlbGameProjectionsGrid';
import SportPredictionsPage, {
  type GroupsContext,
  type PropGroup,
} from '@/components/yetai/SportPredictionsPage';
import {
  formatNumber,
  formatString,
  type ColumnDef,
} from '@/components/PredictionsTable';

function formatSignedEdge(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (Number.isNaN(n)) return formatString(value);
  const sign = n > 0 ? '+' : '';
  return `${sign}${n.toFixed(1)}`;
}

function formatPickConfidence(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (Number.isNaN(n)) return formatString(value);
  return `${Math.round(n)}%`;
}

const STRIKEOUT_BASE_COLUMNS: ColumnDef[] = [
  { key: 'pitcher_name', label: 'Pitcher', format: (v) => formatString(v) },
  { key: 'projected_strikeouts', label: 'Proj K', align: 'right', mono: true, format: (v) => formatNumber(v, 1) },
  { key: 'projected_innings_pitched', label: 'Proj IP', align: 'right', mono: true, format: (v) => formatNumber(v, 1) },
  { key: 'fanduel_line', label: 'FD Line', align: 'right', mono: true, format: (v) => formatNumber(v, 1) },
  { key: 'k_edge', label: 'K Edge', align: 'right', mono: true, format: (v) => formatSignedEdge(v) },
  {
    key: 'yetai_pick',
    label: 'YetAI Pick',
    format: (v, row) => formatString(v ?? row.fanduel_over_under),
  },
  {
    key: 'pick_confidence',
    label: 'Confidence',
    align: 'right',
    mono: true,
    format: (v) => formatPickConfidence(v),
  },
];

const STRIKEOUT_ACTUAL_COLUMNS: ColumnDef[] = [
  { key: 'actual_strikeouts', label: 'Actual K', align: 'right', mono: true, format: (v) => formatNumber(v, 0) },
  { key: 'actual_innings_pitched', label: 'Actual IP', align: 'right', mono: true, format: (v) => formatNumber(v, 1) },
];

const HITS_BASE_COLUMNS: ColumnDef[] = [
  { key: 'batter_name', label: 'Batter', format: (v) => formatString(v) },
  { key: 'projected_hits', label: 'Proj H', align: 'right', mono: true, format: (v) => formatNumber(v, 0) },
];

const HITS_ACTUAL_COLUMN: ColumnDef = {
  key: 'actual_hits',
  label: 'Actual H',
  align: 'right',
  mono: true,
  format: (v) => formatNumber(v, 0),
};

const HOMERS_BASE_COLUMNS: ColumnDef[] = [
  { key: 'batter_name', label: 'Batter', format: (v) => formatString(v) },
  { key: 'projected_homers', label: 'Proj HR', align: 'right', mono: true, format: (v) => formatNumber(v, 0) },
];

const HOMERS_ACTUAL_COLUMN: ColumnDef = {
  key: 'actual_homers',
  label: 'Actual HR',
  align: 'right',
  mono: true,
  format: (v) => formatNumber(v, 0),
};

const HR_COLUMNS: ColumnDef[] = [
  { key: 'player_name', label: 'Hitter', format: (v) => formatString(v) },
  { key: 'team', label: 'Team', format: (v) => formatString(v) },
  { key: 'opponent', label: 'Opp', format: (v) => formatString(v) },
  { key: 'opponent_pitcher', label: 'vs Pitcher', format: (v) => formatString(v) },
  { key: 'venue_name', label: 'Venue', format: (v) => formatString(v) },
];

function buildGroups({ isPastDate }: GroupsContext): PropGroup[] {
  // On past dates we surface actuals next to projections so users can grade
  // each call at a glance. On today/future, those columns would only show
  // null placeholders, so we hide them.
  return [
    {
      title: 'Pitcher Strikeout Projections',
      responseKey: 'strikeout_projections',
      columns: isPastDate
        ? [...STRIKEOUT_BASE_COLUMNS, ...STRIKEOUT_ACTUAL_COLUMNS]
        : STRIKEOUT_BASE_COLUMNS,
    },
    {
      title: 'Projected Hits',
      responseKey: 'projected_hits',
      columns: isPastDate
        ? [...HITS_BASE_COLUMNS, HITS_ACTUAL_COLUMN]
        : HITS_BASE_COLUMNS,
    },
    {
      title: 'Projected Home Runs',
      responseKey: 'projected_homers',
      columns: isPastDate
        ? [...HOMERS_BASE_COLUMNS, HOMERS_ACTUAL_COLUMN]
        : HOMERS_BASE_COLUMNS,
    },
    {
      title: 'Home Run Predictions (ML)',
      responseKey: 'home_run_predictions',
      columns: HR_COLUMNS,
    },
  ];
}

export default function MLBPredictionsPage() {
  return (
    <SportPredictionsPage
      sport="mlb"
      leagueLabel="MLB"
      emoji="⚾"
      subtitle="Game slate, strikeouts, projected hits/HR boards, and ML home run picks."
      topSection={({ data, loading }) => (
        <>
          <h2 className="type-section-title" style={{ margin: '0 0 8px' }}>
            Game projections
          </h2>
          <MlbGameProjectionsGrid
            rows={(data?.game_projections as Array<Record<string, unknown>>) ?? []}
            loading={loading}
          />
        </>
      )}
      accuracySummary={({ date }) => <AccuracySummary sport="mlb" date={date} />}
      groups={buildGroups}
    />
  );
}
