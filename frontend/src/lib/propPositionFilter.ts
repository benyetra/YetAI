export type PositionFilter = 'All' | 'RB' | 'WR' | 'TE';

export const RECV_POSITION_FILTERS: PositionFilter[] = ['All', 'RB', 'WR', 'TE'];

export function filterRowsByPosition<T extends Record<string, unknown>>(
  rows: T[],
  positionKey: string,
  filter: PositionFilter,
): T[] {
  if (filter === 'All') return rows;
  return rows.filter(
    (row) => String(row[positionKey] ?? '').toUpperCase() === filter,
  );
}
