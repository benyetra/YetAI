'use client';

import {
  PredictionsTable,
  formatNumber,
  formatString,
  type ColumnDef,
} from '@/components/PredictionsTable';

const TOTALS_COLUMNS: ColumnDef[] = [
  { key: 'away_team_name', label: 'Away', format: (v) => formatString(v) },
  { key: 'home_team_name', label: 'Home', format: (v) => formatString(v) },
  {
    key: 'projected_total',
    label: 'Proj',
    align: 'right',
    mono: true,
    format: (v) => formatNumber(v, 1),
  },
  {
    key: 'market_total',
    label: 'Line',
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

export default function NbaTotalsProjectionsTable({
  rows,
  loading,
}: {
  rows: Array<Record<string, unknown>>;
  loading?: boolean;
}) {
  if (loading) {
    return (
      <section className="card" style={{ padding: 24, textAlign: 'center' }}>
        <p className="dim">Loading game totals…</p>
      </section>
    );
  }

  if (!rows.length) {
    return (
      <section className="card" style={{ padding: 24, textAlign: 'center' }}>
        <p className="dim">No totals projections for this date.</p>
      </section>
    );
  }

  return (
    <PredictionsTable
      title="Game totals (O/U)"
      columns={TOTALS_COLUMNS}
      rows={rows}
    />
  );
}
