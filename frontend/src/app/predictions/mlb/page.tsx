'use client';

import MlbGameProjectionsGrid from '@/components/yetai/MlbGameProjectionsGrid';
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

const HITS_COLUMNS: ColumnDef[] = [
  { key: 'batter_name', label: 'Batter', format: (v) => formatString(v) },
  { key: 'projected_hits', label: 'Proj H', align: 'right', mono: true, format: (v) => formatNumber(v, 0) },
  { key: 'actual_hits', label: 'Actual', align: 'right', mono: true, format: (v) => formatNumber(v, 0) },
];

const HOMERS_COLUMNS: ColumnDef[] = [
  { key: 'batter_name', label: 'Batter', format: (v) => formatString(v) },
  { key: 'projected_homers', label: 'Proj HR', align: 'right', mono: true, format: (v) => formatNumber(v, 0) },
  { key: 'actual_homers', label: 'Actual', align: 'right', mono: true, format: (v) => formatNumber(v, 0) },
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
      groups={[
        { title: 'Pitcher Strikeout Projections', responseKey: 'strikeout_projections', columns: STRIKEOUT_COLUMNS },
        { title: 'Projected Hits', responseKey: 'projected_hits', columns: HITS_COLUMNS },
        { title: 'Projected Home Runs', responseKey: 'projected_homers', columns: HOMERS_COLUMNS },
        { title: 'Home Run Predictions (ML)', responseKey: 'home_run_predictions', columns: HR_COLUMNS },
      ]}
    />
  );
}
