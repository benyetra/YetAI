'use client';

import AccuracySummary from '@/components/yetai/AccuracySummary';
import GameProjectionsSection from '@/components/yetai/GameProjectionsSection';
import SportPredictionsPage from '@/components/yetai/SportPredictionsPage';
import {
  formatNumber,
  formatString,
  type ColumnDef,
} from '@/components/PredictionsTable';

const GOALIE_COLUMNS: ColumnDef[] = [
  { key: 'goalie_name', label: 'Goalie', format: (v) => formatString(v) },
  { key: 'opponent_team_name', label: 'Opp', format: (v) => formatString(v) },
  { key: 'predicted_saves', label: 'Proj Saves', align: 'right', mono: true, format: (v) => formatNumber(v, 1) },
  { key: 'saves_line', label: 'Saves Line', align: 'right', mono: true, format: (v) => formatNumber(v, 1) },
  { key: 'betting_recommendation', label: 'Pick', format: (v) => formatString(v) },
  { key: 'confidence', label: 'Conf', align: 'right', mono: true, format: (v) => formatNumber(v, 2) },
];

const SHOTS_COLUMNS: ColumnDef[] = [
  { key: 'player_name', label: 'Player', format: (v) => formatString(v) },
  { key: 'opponent_team_name', label: 'Opp', format: (v) => formatString(v) },
  { key: 'predicted_shots', label: 'Proj SOG', align: 'right', mono: true, format: (v) => formatNumber(v, 1) },
  { key: 'shots_line', label: 'Line', align: 'right', mono: true, format: (v) => formatNumber(v, 1) },
  { key: 'betting_recommendation', label: 'Pick', format: (v) => formatString(v) },
  { key: 'confidence', label: 'Conf', align: 'right', mono: true, format: (v) => formatNumber(v, 2) },
];

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
        { title: 'Goalie Predictions', responseKey: 'goalie_predictions', columns: GOALIE_COLUMNS },
        { title: 'Player Shots Predictions', responseKey: 'player_shots', columns: SHOTS_COLUMNS },
      ]}
    />
  );
}
