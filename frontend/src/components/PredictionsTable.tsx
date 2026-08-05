'use client';

import { ReactNode, useMemo, useState } from 'react';
import { AlertCircle, ChevronDown, ChevronRight, Lock } from 'lucide-react';

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
  /** When false, column header is not clickable for sort. Default true. */
  sortable?: boolean;
};

export type SortState = { key: string; dir: 'asc' | 'desc' };

type PredictionsTableProps = {
  title: string;
  rows: Array<Record<string, unknown>>;
  columns: ColumnDef[];
  loading?: boolean;
  emptyMessage?: string;
  /** Controlled expand/collapse; omit for internal state only. */
  expanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
  /** Optional per-row class for highlighting value plays. */
  rowClassName?: (row: Record<string, unknown>) => string | undefined;
};

/** Person-name columns — sort by last name, not first. */
const PERSON_NAME_SORT_KEYS = new Set([
  'player_name',
  'pitcher_name',
  'batter_name',
  'goalie_name',
  'qb_player_name',
  'kicker_player_name',
]);

const NAME_SUFFIXES = new Set(['jr', 'jr.', 'sr', 'sr.', 'ii', 'iii', 'iv', 'v']);

/** Sort key for "First Last" / "First Middle Last Jr." → last name primary. */
export function personNameSortKey(name: unknown): string {
  if (name === null || name === undefined || name === '') return '';
  const parts = String(name)
    .trim()
    .replace(/,/g, ' ')
    .split(/\s+/)
    .filter(Boolean);
  if (parts.length === 0) return '';
  if (parts.length === 1) return parts[0].toLowerCase();

  let lastIdx = parts.length - 1;
  while (lastIdx > 0 && NAME_SUFFIXES.has(parts[lastIdx].toLowerCase())) {
    lastIdx -= 1;
  }
  const last = parts[lastIdx];
  const rest = [...parts.slice(0, lastIdx), ...parts.slice(lastIdx + 1)].join(' ');
  return `${last} ${rest}`.toLowerCase();
}

function cellSortValue(value: unknown, key?: string): number | string {
  if (key && PERSON_NAME_SORT_KEYS.has(key)) {
    return personNameSortKey(value);
  }
  if (value === null || value === undefined || value === '') return '';
  if (typeof value === 'number') return value;
  const asString = String(value).trim();
  const n = parseFloat(asString);
  if (!Number.isNaN(n) && asString !== '') return n;
  return asString.toLowerCase();
}

export function comparePredictionRows(
  a: Record<string, unknown>,
  b: Record<string, unknown>,
  key: string,
  dir: 'asc' | 'desc'
): number {
  const va = cellSortValue(a[key], key);
  const vb = cellSortValue(b[key], key);
  let cmp = 0;
  if (typeof va === 'number' && typeof vb === 'number') {
    cmp = va - vb;
  } else {
    cmp = String(va).localeCompare(String(vb), undefined, { numeric: true, sensitivity: 'base' });
  }
  return dir === 'asc' ? cmp : -cmp;
}

function SortIndicator({ active, dir }: { active: boolean; dir?: 'asc' | 'desc' }) {
  if (!active) {
    return <span className="data-table-sort data-table-sort-idle" aria-hidden>↕</span>;
  }
  return (
    <span className="data-table-sort" aria-hidden>
      {dir === 'asc' ? '↑' : '↓'}
    </span>
  );
}

export function PredictionsTable({
  title,
  rows,
  columns,
  loading,
  emptyMessage = 'No predictions available for this date.',
  expanded: expandedProp,
  onExpandedChange,
  rowClassName,
}: PredictionsTableProps) {
  const [expandedInternal, setExpandedInternal] = useState(true);
  const [sort, setSort] = useState<SortState | null>(null);

  const expanded = expandedProp ?? expandedInternal;
  const setExpanded = (next: boolean) => {
    if (expandedProp === undefined) {
      setExpandedInternal(next);
    }
    onExpandedChange?.(next);
  };

  const sortedRows = useMemo(() => {
    if (!sort) return rows;
    return [...rows].sort((a, b) => comparePredictionRows(a, b, sort.key, sort.dir));
  }, [rows, sort]);

  const handleSort = (column: ColumnDef) => {
    if (column.sortable === false) return;
    setSort((prev) => {
      if (prev?.key !== column.key) return { key: column.key, dir: 'asc' };
      if (prev.dir === 'asc') return { key: column.key, dir: 'desc' };
      return null;
    });
  };

  return (
    <section className="card predictions-table-card" style={{ padding: 0, overflow: 'hidden' }}>
      <header className="card-head predictions-table-head">
        <button
          type="button"
          className="predictions-table-toggle"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
        >
          {expanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
          <h2>{title}</h2>
        </button>
        {!loading && (
          <span className="card-meta">
            {rows.length} {rows.length === 1 ? 'projection' : 'projections'}
          </span>
        )}
      </header>

      {expanded && (
        <>
          {loading ? (
            <div className="card-body-empty">Loading…</div>
          ) : rows.length === 0 ? (
            <div className="card-body-empty">{emptyMessage}</div>
          ) : (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    {columns.map((c) => {
                      const sortable = c.sortable !== false;
                      const isActive = sort?.key === c.key;
                      const align =
                        c.align === 'right' ? 'text-right' : c.align === 'center' ? 'text-center' : '';
                      if (!sortable) {
                        return (
                          <th key={c.key} scope="col" className={align}>
                            {c.label}
                          </th>
                        );
                      }
                      return (
                        <th key={c.key} scope="col" className={`sortable ${align}`}>
                          <button
                            type="button"
                            className="data-table-sort-btn"
                            onClick={() => handleSort(c)}
                            aria-sort={
                              isActive ? (sort!.dir === 'asc' ? 'ascending' : 'descending') : 'none'
                            }
                          >
                            <span>{c.label}</span>
                            <SortIndicator active={isActive} dir={isActive ? sort!.dir : undefined} />
                          </button>
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {sortedRows.map((row, i) => (
                    <tr
                      key={(row.id as number | string) ?? i}
                      className={rowClassName?.(row) ?? undefined}
                    >
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
        </>
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
