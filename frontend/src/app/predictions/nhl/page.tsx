'use client';

import AccuracySummary from '@/components/yetai/AccuracySummary';
import GameProjectionsSection from '@/components/yetai/GameProjectionsSection';
import SportPredictionsPage from '@/components/yetai/SportPredictionsPage';
import {
  NHL_GOALIE_COLUMNS,
  NHL_SHOTS_COLUMNS,
  propRowClassName,
} from '@/lib/propProjectionDisplay';

export default function NHLPredictionsPage() {
  return (
    <SportPredictionsPage
      sport="nhl"
      leagueLabel="NHL"
      emoji="🏒"
      subtitle="Game slate totals O/U, goalie saves, and player shots on goal."
      topSection={({ data, loading, isPastDate }) => (
        <GameProjectionsSection
          variant="nhl"
          data={data}
          loading={loading}
          isPastDate={isPastDate}
        />
      )}
      accuracySummary={({ date }) => <AccuracySummary sport="nhl" date={date} />}
      groups={[
        {
          title: 'Goalie Predictions',
          responseKey: 'goalie_predictions',
          columns: NHL_GOALIE_COLUMNS,
          rowClassName: propRowClassName,
        },
        {
          title: 'Player Shots Predictions',
          responseKey: 'player_shots',
          columns: NHL_SHOTS_COLUMNS,
          rowClassName: propRowClassName,
        },
      ]}
    />
  );
}
