'use client';

import AccuracySummary from '@/components/yetai/AccuracySummary';
import GameProjectionsSection from '@/components/yetai/GameProjectionsSection';
import SportPredictionsPage, {
  type GroupsContext,
  type PropGroup,
} from '@/components/yetai/SportPredictionsPage';
import {
  formatNumber,
  formatString,
  type ColumnDef,
} from '@/components/PredictionsTable';
import { MLB_DISCOVERY_GROUPS } from '@/lib/propDiscoveryConfigs';
import {
  MLB_STRIKEOUT_COLUMNS_BASE,
  OPPONENT_TEAM_COLUMN,
  TEAM_COLUMN,
  propRowClassName,
} from '@/lib/propProjectionDisplay';

const STRIKEOUT_ACTUAL_COLUMNS: ColumnDef[] = [
  { key: 'actual_strikeouts', label: 'Actual K', align: 'right', mono: true, format: (v) => formatNumber(v, 0) },
  { key: 'actual_innings_pitched', label: 'Actual IP', align: 'right', mono: true, format: (v) => formatNumber(v, 1) },
];

const HITS_BASE_COLUMNS: ColumnDef[] = [
  { key: 'batter_name', label: 'Batter', format: (v) => formatString(v) },
  TEAM_COLUMN,
  OPPONENT_TEAM_COLUMN,
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
  TEAM_COLUMN,
  OPPONENT_TEAM_COLUMN,
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
  TEAM_COLUMN,
  OPPONENT_TEAM_COLUMN,
  { key: 'opponent_pitcher', label: 'vs Pitcher', format: (v) => formatString(v) },
  { key: 'venue_name', label: 'Venue', format: (v) => formatString(v) },
];

function buildGroups({ isPastDate }: GroupsContext): PropGroup[] {
  return [
    {
      title: 'Pitcher Strikeout Projections',
      responseKey: 'strikeout_projections',
      columns: isPastDate
        ? [...MLB_STRIKEOUT_COLUMNS_BASE, ...STRIKEOUT_ACTUAL_COLUMNS]
        : [...MLB_STRIKEOUT_COLUMNS_BASE],
      rowClassName: propRowClassName,
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
      topSection={({ data, loading, isPastDate }) => (
        <GameProjectionsSection
          variant="mlb"
          data={data}
          loading={loading}
          isPastDate={isPastDate}
        />
      )}
      accuracySummary={({ date }) => <AccuracySummary sport="mlb" date={date} />}
      groups={buildGroups}
      discoveryGroups={MLB_DISCOVERY_GROUPS}
    />
  );
}
