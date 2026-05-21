'use client';

import NbaTotalsProjectionsTable from '@/components/yetai/NbaTotalsProjectionsTable';
import SportPredictionsPage from '@/components/yetai/SportPredictionsPage';
import WnbaSpreadProjectionsTable from '@/components/yetai/WnbaSpreadProjectionsTable';
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
      subtitle="Game totals O/U and spread/win-probability projections. Player props (points, assists, rebounds) shipping in Phase 2."
      topSection={({ data, loading }) => (
        <>
          <WnbaSpreadProjectionsTable
            rows={(data?.spreads as Array<Record<string, unknown>>) ?? []}
            loading={loading}
          />
          <NbaTotalsProjectionsTable
            rows={(data?.totals as Array<Record<string, unknown>>) ?? []}
            loading={loading}
          />
        </>
      )}
      groups={PROP_GROUPS}
    />
  );
}
