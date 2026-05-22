'use client';

import {
  PredictionsTable,
  formatNumber,
  formatString,
  type ColumnDef,
} from '@/components/PredictionsTable';

const SPREAD_COLUMNS: ColumnDef[] = [
  { key: 'away_team_name', label: 'Away', format: (v) => formatString(v) },
  { key: 'home_team_name', label: 'Home', format: (v) => formatString(v) },
  {
    key: 'projected_margin',
    label: 'Proj Margin',
    align: 'right',
    mono: true,
    format: (v) => formatNumber(v, 1),
  },
  {
    key: 'home_win_prob',
    label: 'Home Win %',
    align: 'right',
    mono: true,
    format: (v) => (v == null ? '—' : `${(Number(v) * 100).toFixed(1)}%`),
  },
  {
    key: 'market_spread_home',
    label: 'Mkt Spread',
    align: 'right',
    mono: true,
    format: (v) => formatNumber(v, 1),
  },
  {
    key: 'edge',
    label: 'Edge',
    align: 'right',
    mono: true,
    format: (v) => formatNumber(v, 1),
  },
  { key: 'recommendation', label: 'Pick', format: (v) => formatString(v) },
  {
    key: 'confidence_score',
    label: 'Conf',
    align: 'right',
    mono: true,
    format: (v) => formatNumber(v, 2),
  },
];

export default function SpreadProjectionsTable({
  rows,
  loading,
}: {
  rows: Array<Record<string, unknown>>;
  loading?: boolean;
}) {
  if (loading) {
    return (
      <section className="card" style={{ padding: 24, textAlign: 'center' }}>
        <p className="dim">Loading spread projections…</p>
      </section>
    );
  }

  if (!rows.length) {
    return (
      <section className="card" style={{ padding: 24, textAlign: 'center' }}>
        <p className="dim">No spread projections for this date.</p>
      </section>
    );
  }

  return (
    <PredictionsTable
      title="Spread / win-probability"
      columns={SPREAD_COLUMNS}
      rows={rows}
    />
  );
}
