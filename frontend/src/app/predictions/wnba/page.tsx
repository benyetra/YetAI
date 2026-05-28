'use client';

import AccuracySummary from '@/components/yetai/AccuracySummary';
import GameProjectionsGrid from '@/components/yetai/MlbGameProjectionsGrid';
import SportPredictionsPage from '@/components/yetai/SportPredictionsPage';
import {
  formatNumber,
  formatString,
  type ColumnDef,
} from '@/components/PredictionsTable';
import { mergeWnbaGameProjections } from '@/lib/mergeWnbaGameProjections';
import { useMemo } from 'react';

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

function WnbaGameProjectionsSection({
  data,
  loading,
  isPastDate,
}: {
  data: Record<string, Array<Record<string, unknown>>> | null;
  loading: boolean;
  isPastDate: boolean;
}) {
  const gameRows = useMemo(
    () =>
      mergeWnbaGameProjections(
        (data?.spreads as Array<Record<string, unknown>>) ?? [],
        (data?.totals as Array<Record<string, unknown>>) ?? [],
      ),
    [data?.spreads, data?.totals],
  );

  return (
    <>
      <h2 className="type-section-title" style={{ margin: '0 0 8px' }}>
        Game projections
      </h2>
      <GameProjectionsGrid
        rows={gameRows}
        loading={loading}
        isPastDate={isPastDate}
        variant="basketball"
      />
    </>
  );
}

export default function WNBAPredictionsPage() {
  return (
    <SportPredictionsPage
      sport="wnba"
      leagueLabel="WNBA"
      emoji="🏀"
      subtitle="Game slate, spread/win-probability, totals O/U, and player props (points, assists, rebounds)."
      topSection={({ data, loading, isPastDate }) => (
        <WnbaGameProjectionsSection data={data} loading={loading} isPastDate={isPastDate} />
      )}
      accuracySummary={({ date }) => <AccuracySummary sport="wnba" date={date} />}
      groups={PROP_GROUPS}
    />
  );
}
