'use client';

import AccuracySummary from '@/components/yetai/AccuracySummary';
import GameProjectionsSection from '@/components/yetai/GameProjectionsSection';
import SportPredictionsPage from '@/components/yetai/SportPredictionsPage';
import {
  formatNumber,
  formatString,
  type ColumnDef,
} from '@/components/PredictionsTable';
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

export default function NFLPredictionsPage() {
  return (
    <SportPredictionsPage
      sport="nfl"
      leagueLabel="NFL"
      emoji="🏈"
      subtitle="Game slate projections plus quarterback passing and kicker field goal predictions."
      topSection={({ data, loading, isPastDate }) => (
        <GameProjectionsSection
          variant="nfl"
          data={data}
          loading={loading}
          isPastDate={isPastDate}
        />
      )}
      accuracySummary={({ date }) => <AccuracySummary sport="nfl" date={date} />}
      groups={[
        {
          title: 'Quarterback Predictions',
          responseKey: 'qb_predictions',
          columns: NFL_QB_COLUMNS,
          rowClassName: propRowClassName,
        },
        { title: 'Kicker Predictions', responseKey: 'kicker_predictions', columns: KICKER_COLUMNS },
      ]}
    />
  );
}
