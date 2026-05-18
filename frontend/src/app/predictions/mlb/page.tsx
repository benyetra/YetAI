'use client';

import SportPredictionsPage from '@/components/yetai/SportPredictionsPage';
import {
  formatNumber,
  formatString,
  type ColumnDef,
} from '@/components/PredictionsTable';

const STRIKEOUT_COLUMNS: ColumnDef[] = [
  { key: 'pitcher_name', label: 'Pitcher', format: (v) => formatString(v) },
  { key: 'projected_strikeouts', label: 'Proj K', align: 'right', mono: true, format: (v) => formatNumber(v, 1) },
  { key: 'projected_innings_pitched', label: 'Proj IP', align: 'right', mono: true, format: (v) => formatNumber(v, 1) },
  { key: 'fanduel_line', label: 'FD Line', align: 'right', mono: true, format: (v) => formatNumber(v, 1) },
  { key: 'fanduel_over_under', label: 'FD O/U', format: (v) => formatString(v) },
];

const HR_COLUMNS: ColumnDef[] = [
  { key: 'player_name', label: 'Hitter', format: (v) => formatString(v) },
  { key: 'team', label: 'Team', format: (v) => formatString(v) },
  { key: 'opponent', label: 'Opp', format: (v) => formatString(v) },
  { key: 'opponent_pitcher', label: 'vs Pitcher', format: (v) => formatString(v) },
  { key: 'venue_name', label: 'Venue', format: (v) => formatString(v) },
];

export default function MLBPredictionsPage() {
  return (
    <SportPredictionsPage
      sport="mlb"
      leagueLabel="MLB"
      emoji="⚾"
      subtitle="Pitcher strikeout projections and home run picks."
      groups={[
        { title: 'Pitcher Strikeout Projections', responseKey: 'strikeout_projections', columns: STRIKEOUT_COLUMNS },
        { title: 'Home Run Predictions', responseKey: 'home_run_predictions', columns: HR_COLUMNS },
      ]}
    />
  );
}
