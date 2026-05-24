'use client';

import AccuracySummary from '@/components/yetai/AccuracySummary';
import NbaTotalsProjectionsTable from '@/components/yetai/NbaTotalsProjectionsTable';
import SpreadProjectionsTable from '@/components/yetai/SpreadProjectionsTable';
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
    { key: 'fanduel_line', label: 'FD Line', align: 'right', mono: true, format: (v) => formatNumber(v, 1) },
    { key: 'fanduel_over_under', label: 'FD O/U', format: (v) => formatString(v) },
  ];
}

const PROP_GROUPS = [
  { title: 'Points', responseKey: 'points', columns: propColumns('projected_points', 'Proj Pts') },
  { title: 'Assists', responseKey: 'assists', columns: propColumns('projected_assists', 'Proj Ast') },
  { title: 'Rebounds', responseKey: 'rebounds', columns: propColumns('projected_rebounds', 'Proj Reb') },
  { title: 'Three-Pointers', responseKey: 'three_point', columns: propColumns('projected_three_pt_made', 'Proj 3PM') },
  { title: 'Steals', responseKey: 'steals', columns: propColumns('projected_steals', 'Proj Stl') },
  { title: 'Blocks', responseKey: 'blocks', columns: propColumns('projected_blocks', 'Proj Blk') },
  { title: 'PRA (Pts + Reb + Ast)', responseKey: 'pra', columns: propColumns('projected_pra', 'Proj PRA') },
];

export default function NBAPredictionsPage() {
  return (
    <SportPredictionsPage
      sport="nba"
      leagueLabel="NBA"
      emoji="🏀"
      subtitle="Game totals O/U, spread/win-probability, plus points, assists, rebounds, threes, steals, blocks, and PRA."
      topSection={({ data, loading }) => (
        <>
          <SpreadProjectionsTable
            rows={(data?.spreads as Array<Record<string, unknown>>) ?? []}
            loading={loading}
          />
          <NbaTotalsProjectionsTable
            rows={(data?.totals as Array<Record<string, unknown>>) ?? []}
            loading={loading}
          />
        </>
      )}
      accuracySummary={({ date }) => <AccuracySummary sport="nba" date={date} />}
      groups={PROP_GROUPS}
    />
  );
}
