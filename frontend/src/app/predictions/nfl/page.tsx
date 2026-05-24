'use client';

import AccuracySummary from '@/components/yetai/AccuracySummary';
import SportPredictionsPage from '@/components/yetai/SportPredictionsPage';
import {
  formatNumber,
  formatString,
  type ColumnDef,
} from '@/components/PredictionsTable';

const QB_COLUMNS: ColumnDef[] = [
  { key: 'qb_player_name', label: 'QB', format: (v) => formatString(v) },
  { key: 'opponent_team_name', label: 'Opp', format: (v) => formatString(v) },
  { key: 'predicted_passing_yards', label: 'Pass Yds', align: 'right', mono: true, format: (v) => formatNumber(v, 0) },
  { key: 'predicted_completions', label: 'Comp', align: 'right', mono: true, format: (v) => formatNumber(v, 1) },
  { key: 'predicted_touchdowns', label: 'TD', align: 'right', mono: true, format: (v) => formatNumber(v, 1) },
  { key: 'betting_recommendation', label: 'Pick', format: (v) => formatString(v) },
];

const KICKER_COLUMNS: ColumnDef[] = [
  { key: 'kicker_player_name', label: 'Kicker', format: (v) => formatString(v) },
  { key: 'opponent_team_name', label: 'Opp', format: (v) => formatString(v) },
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
      subtitle="Quarterback passing projections and kicker field goal predictions."
      accuracySummary={({ date }) => <AccuracySummary sport="nfl" date={date} />}
      groups={[
        { title: 'Quarterback Predictions', responseKey: 'qb_predictions', columns: QB_COLUMNS },
        { title: 'Kicker Predictions', responseKey: 'kicker_predictions', columns: KICKER_COLUMNS },
      ]}
    />
  );
}
