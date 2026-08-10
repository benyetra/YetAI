'use client';

import AccuracySummary from '@/components/yetai/AccuracySummary';
import GameProjectionsSection from '@/components/yetai/GameProjectionsSection';
import SportPredictionsPage, {
  type PropGroup,
} from '@/components/yetai/SportPredictionsPage';
import {
  formatNumber,
  formatString,
  type ColumnDef,
} from '@/components/PredictionsTable';
import {
  ANYTIME_TD_COLUMNS,
  isAnytimeTdUiEnabled,
} from '@/lib/anytimeTdDisplay';
import {
  NFL_QB_COLUMNS,
  OPPONENT_TEAM_COLUMN,
  TEAM_COLUMN,
  propRowClassName,
} from '@/lib/propProjectionDisplay';

const KICKER_COLUMNS: ColumnDef[] = [
  { key: 'kicker_player_name', label: 'Kicker', format: (v) => formatString(v) },
  TEAM_COLUMN,
  OPPONENT_TEAM_COLUMN,
  { key: 'predicted_fg_attempts', label: 'FGA', align: 'right', mono: true, format: (v) => formatNumber(v, 1) },
  { key: 'predicted_fg_made', label: 'FGM', align: 'right', mono: true, format: (v) => formatNumber(v, 1) },
  { key: 'predicted_success_rate', label: 'Hit %', align: 'right', mono: true, format: (v) => formatNumber(v, 1) },
];

function buildNflPropGroups(): PropGroup[] {
  const groups: PropGroup[] = [
    {
      title: 'Quarterback Predictions',
      responseKey: 'qb_predictions',
      columns: NFL_QB_COLUMNS,
      rowClassName: propRowClassName,
    },
    {
      title: 'Kicker Predictions',
      responseKey: 'kicker_predictions',
      columns: KICKER_COLUMNS,
    },
  ];
  if (isAnytimeTdUiEnabled()) {
    groups.push({
      title: 'Anytime Touchdowns',
      responseKey: 'anytime_td_predictions',
      columns: ANYTIME_TD_COLUMNS,
      rowClassName: propRowClassName,
    });
  }
  return groups;
}

const NFL_SUBTITLE = isAnytimeTdUiEnabled()
  ? 'Game slate projections plus quarterback passing, kicker field goals, and model anytime touchdown predictions.'
  : 'Game slate projections plus quarterback passing and kicker field goal predictions.';

export default function NFLPredictionsPage() {
  return (
    <SportPredictionsPage
      sport="nfl"
      leagueLabel="NFL"
      emoji="🏈"
      subtitle={NFL_SUBTITLE}
      topSection={({ data, loading, isPastDate }) => (
        <GameProjectionsSection
          variant="nfl"
          data={data}
          loading={loading}
          isPastDate={isPastDate}
        />
      )}
      accuracySummary={({ date }) => <AccuracySummary sport="nfl" date={date} />}
      groups={buildNflPropGroups()}
    />
  );
}
