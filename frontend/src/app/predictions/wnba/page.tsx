'use client';

import AccuracySummary from '@/components/yetai/AccuracySummary';
import GameProjectionsSection from '@/components/yetai/GameProjectionsSection';
import SportPredictionsPage from '@/components/yetai/SportPredictionsPage';
import {
  formatNumber,
  formatString,
  type ColumnDef,
} from '@/components/PredictionsTable';

function propColumns(propKey: string, propLabel: string): ColumnDef[] {
  return [
    { key: 'player_name', label: 'Player', format: (v) => formatString(v) },
    { key: 'opponent_team_name', label: 'Opp', format: (v) => formatString(v) },
    { key: propKey, label: propLabel, align: 'right', mono: true, format: (v) => formatNumber(v, 1) },
    { key: 'market_line', label: 'Line', align: 'right', mono: true, format: (v) => formatNumber(v, 1) },
    { key: 'recommendation', label: 'Pick', format: (v) => formatString(v) },
  ];
}

const PROP_GROUPS = [
  { title: 'Points', responseKey: 'points', columns: propColumns('projected_points', 'Proj Pts') },
  { title: 'Assists', responseKey: 'assists', columns: propColumns('projected_assists', 'Proj Ast') },
  { title: 'Rebounds', responseKey: 'rebounds', columns: propColumns('projected_rebounds', 'Proj Reb') },
];

export default function WNBAPredictionsPage() {
  return (
    <SportPredictionsPage
      sport="wnba"
      leagueLabel="WNBA"
      emoji="🏀"
      subtitle="Game slate, spread/win-probability, totals O/U, and player props (points, assists, rebounds)."
      topSection={({ data, loading, isPastDate }) => (
        <GameProjectionsSection
          variant="wnba"
          data={data}
          loading={loading}
          isPastDate={isPastDate}
        />
      )}
      accuracySummary={({ date }) => <AccuracySummary sport="wnba" date={date} />}
      groups={PROP_GROUPS}
    />
  );
}
