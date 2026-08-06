'use client';

import {
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { VaultHelp } from './VaultHelp';

export type VaultSortDir = 'asc' | 'desc';
export type VaultSortValue = string | number | boolean | null | undefined;

export type VaultSortableColumn<T> = {
  key: string;
  /** Plain header label (no interactive children — those go in `help`). */
  label: ReactNode;
  help?: string;
  helpLabel?: string;
  sortValue: (row: T) => VaultSortValue;
  cell: (row: T) => ReactNode;
  /** Render as <th scope="row"> instead of <td>. */
  rowHeader?: boolean;
  cellClassName?: string | ((row: T) => string | undefined);
  headerClassName?: string;
  sortable?: boolean;
};

export type VaultSortState = {
  key: string;
  dir: VaultSortDir;
};

type Props<T> = {
  rows: T[];
  columns: VaultSortableColumn<T>[];
  rowKey: (row: T) => string | number;
  rowClassName?: (row: T, index: number) => string | undefined;
  initialSort?: VaultSortState | null;
  className?: string;
  caption?: string;
};

export function compareVaultSortValues(
  a: VaultSortValue,
  b: VaultSortValue,
  dir: VaultSortDir,
): number {
  const emptyA = a == null || a === '';
  const emptyB = b == null || b === '';
  if (emptyA && emptyB) return 0;
  if (emptyA) return 1;
  if (emptyB) return -1;

  let result = 0;
  if (typeof a === 'number' && typeof b === 'number') {
    result = a - b;
  } else if (typeof a === 'boolean' && typeof b === 'boolean') {
    result = Number(a) - Number(b);
  } else {
    result = String(a).localeCompare(String(b), undefined, {
      numeric: true,
      sensitivity: 'base',
    });
  }
  return dir === 'asc' ? result : -result;
}

function SortGlyph({ active, dir }: { active: boolean; dir?: VaultSortDir }) {
  return (
    <span className="vault-sort-glyph" aria-hidden="true">
      {active ? (dir === 'asc' ? '▲' : '▼') : '◇'}
    </span>
  );
}

export function VaultSortableTable<T>({
  rows,
  columns,
  rowKey,
  rowClassName,
  initialSort = null,
  className = 'vault-table',
  caption,
}: Props<T>) {
  const [sort, setSort] = useState<VaultSortState | null>(initialSort);

  const sortedRows = useMemo(() => {
    if (!sort) return rows;
    const column = columns.find((c) => c.key === sort.key);
    if (!column || column.sortable === false) return rows;
    return [...rows].sort((a, b) =>
      compareVaultSortValues(column.sortValue(a), column.sortValue(b), sort.dir),
    );
  }, [columns, rows, sort]);

  const onSort = (column: VaultSortableColumn<T>) => {
    if (column.sortable === false) return;
    setSort((prev) => {
      if (prev?.key !== column.key) return { key: column.key, dir: 'asc' };
      if (prev.dir === 'asc') return { key: column.key, dir: 'desc' };
      return null;
    });
  };

  return (
    <table className={className}>
      {caption ? <caption className="vault-table-caption">{caption}</caption> : null}
      <thead>
        <tr>
          {columns.map((column) => {
            const sortable = column.sortable !== false;
            const active = sort?.key === column.key;
            const headerClass = [
              sortable ? 'vault-th-sortable' : null,
              active ? 'is-sorted' : null,
              column.headerClassName,
            ]
              .filter(Boolean)
              .join(' ');

            const help =
              column.help != null && column.help !== '' ? (
                <VaultHelp
                  text={column.help}
                  label={column.helpLabel ?? `About ${String(column.label)}`}
                />
              ) : null;

            if (!sortable) {
              return (
                <th key={column.key} scope="col" className={column.headerClassName}>
                  <span className="vault-th-static">
                    <span>{column.label}</span>
                    {help}
                  </span>
                </th>
              );
            }

            return (
              <th
                key={column.key}
                scope="col"
                className={headerClass}
                aria-sort={
                  active ? (sort!.dir === 'asc' ? 'ascending' : 'descending') : 'none'
                }
              >
                <span className="vault-th-sort-wrap">
                  <button
                    type="button"
                    className="vault-sort-btn"
                    onClick={() => onSort(column)}
                  >
                    <span className="vault-sort-btn-label">{column.label}</span>
                    <SortGlyph active={active} dir={active ? sort!.dir : undefined} />
                  </button>
                  {help}
                </span>
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {sortedRows.map((row, index) => {
          const classNameRow = rowClassName?.(row, index);
          return (
            <tr key={rowKey(row)} className={classNameRow}>
              {columns.map((column) => {
                const cellClass =
                  typeof column.cellClassName === 'function'
                    ? column.cellClassName(row)
                    : column.cellClassName;
                const content = column.cell(row);
                if (column.rowHeader) {
                  return (
                    <th key={column.key} scope="row" className={cellClass}>
                      {content}
                    </th>
                  );
                }
                return (
                  <td key={column.key} className={cellClass}>
                    {content}
                  </td>
                );
              })}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
