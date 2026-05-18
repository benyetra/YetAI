'use client';

import { ReactNode } from 'react';
import { Lock, AlertCircle } from 'lucide-react';

export function PredictionsPaywall({ onUpgrade }: { onUpgrade: () => void }) {
  return (
    <section className="card" style={{ padding: 40, textAlign: 'center' }}>
      <Lock size={40} style={{ margin: '0 auto 12px', color: 'var(--accent)' }} />
      <h3 className="type-section-title" style={{ marginBottom: 8 }}>Predictions are a PRO feature</h3>
      <p className="dim" style={{ maxWidth: 400, margin: '0 auto 20px', fontSize: 13 }}>
        Upgrade to PRO to unlock ML-powered projections across MLB, NBA, NFL, and NHL.
      </p>
      <button type="button" className="btn btn-primary" onClick={onUpgrade}>
        Upgrade Now
      </button>
    </section>
  );
}

export function PredictionsError({ message }: { message: string }) {
  return (
    <div className="alert alert-error" style={{ display: 'flex', gap: 12, alignItems: 'start' }}>
      <AlertCircle size={18} style={{ flexShrink: 0, marginTop: 2 }} />
      <div>
        <p style={{ fontWeight: 500, margin: 0 }}>Failed to load predictions</p>
        <p className="mono dim" style={{ fontSize: 11, marginTop: 4 }}>
          {message}
        </p>
      </div>
    </div>
  );
}

export type ColumnDef = {
  key: string;
  label: string;
  format?: (value: unknown, row: Record<string, unknown>) => ReactNode;
  align?: 'left' | 'right' | 'center';
  className?: string;
  mono?: boolean;
};

type PredictionsTableProps = {
  title: string;
  rows: Array<Record<string, unknown>>;
  columns: ColumnDef[];
  loading?: boolean;
  emptyMessage?: string;
};

export function PredictionsTable({
  title,
  rows,
  columns,
  loading,
  emptyMessage = 'No predictions available for this date.',
}: PredictionsTableProps) {
  return (
    <section className="card" style={{ padding: 0, overflow: 'hidden' }}>
      <header className="card-head">
        <h2>{title}</h2>
        {!loading && (
          <span className="card-meta">
            {rows.length} {rows.length === 1 ? 'projection' : 'projections'}
          </span>
        )}
      </header>

      {loading ? (
        <div className="card-body-empty">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="card-body-empty">{emptyMessage}</div>
      ) : (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                {columns.map((c) => (
                  <th
                    key={c.key}
                    scope="col"
                    className={
                      c.align === 'right' ? 'text-right' : c.align === 'center' ? 'text-center' : ''
                    }
                  >
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={(row.id as number | string) ?? i}>
                  {columns.map((c) => {
                    const raw = row[c.key];
                    const content = c.format ? c.format(raw, row) : (raw as ReactNode);
                    const align =
                      c.align === 'right' ? 'text-right' : c.align === 'center' ? 'text-center' : '';
                    return (
                      <td
                        key={c.key}
                        className={`${align} ${c.mono || c.align === 'right' ? 'mono' : ''} ${c.className ?? ''}`}
                      >
                        {content as ReactNode}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function formatNumber(v: unknown, digits = 2): string {
  if (v === null || v === undefined || v === '') return '—';
  const n = typeof v === 'number' ? v : parseFloat(String(v));
  if (Number.isNaN(n)) return '—';
  return n.toFixed(digits);
}

export function formatString(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  return String(v);
}
