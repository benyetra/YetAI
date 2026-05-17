'use client';

import { ReactNode } from 'react';
import { Lock, AlertCircle } from 'lucide-react';

export function PredictionsPaywall({ onUpgrade }: { onUpgrade: () => void }) {
  return (
    <div className="bg-white rounded-lg border border-purple-200 p-8 text-center">
      <Lock className="w-10 h-10 mx-auto text-purple-600 mb-3" />
      <h3 className="text-xl font-semibold text-gray-900 mb-2">Predictions are a PRO feature</h3>
      <p className="text-gray-600 mb-5 max-w-md mx-auto">
        Upgrade to PRO or ELITE to unlock ML-powered projections across MLB, NBA, NFL, and NHL.
      </p>
      <button
        onClick={onUpgrade}
        className="bg-purple-600 text-white px-6 py-2.5 rounded-lg hover:bg-purple-700 font-medium transition-colors"
      >
        Upgrade Now
      </button>
    </div>
  );
}

export function PredictionsError({ message }: { message: string }) {
  return (
    <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-start gap-3">
      <AlertCircle className="w-5 h-5 text-red-600 mt-0.5 flex-shrink-0" />
      <div>
        <p className="text-sm font-medium text-red-900">Failed to load predictions</p>
        <p className="text-xs text-red-700 mt-1 font-mono">{message}</p>
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
    <section className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
      <header className="px-6 py-4 border-b border-gray-200 bg-gray-50">
        <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
        {!loading && (
          <p className="text-xs text-gray-500 mt-1">
            {rows.length} {rows.length === 1 ? 'projection' : 'projections'}
          </p>
        )}
      </header>

      {loading ? (
        <div className="px-6 py-12 text-center text-sm text-gray-500">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="px-6 py-12 text-center text-sm text-gray-500">{emptyMessage}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-white">
              <tr>
                {columns.map((c) => (
                  <th
                    key={c.key}
                    scope="col"
                    className={`px-4 py-3 text-xs font-semibold text-gray-700 uppercase tracking-wider ${
                      c.align === 'right'
                        ? 'text-right'
                        : c.align === 'center'
                        ? 'text-center'
                        : 'text-left'
                    }`}
                  >
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-100">
              {rows.map((row, i) => (
                <tr key={(row.id as number | string) ?? i} className="hover:bg-gray-50">
                  {columns.map((c) => {
                    const raw = row[c.key];
                    const content = c.format ? c.format(raw, row) : (raw as ReactNode);
                    return (
                      <td
                        key={c.key}
                        className={`px-4 py-3 whitespace-nowrap text-sm text-gray-800 ${
                          c.align === 'right'
                            ? 'text-right'
                            : c.align === 'center'
                            ? 'text-center'
                            : 'text-left'
                        } ${c.className ?? ''}`}
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
