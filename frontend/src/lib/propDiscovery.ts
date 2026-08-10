/** Client-side player search + best-edges discovery for stat projection pages. */

export const PERSON_NAME_KEYS = [
  'player_name',
  'pitcher_name',
  'batter_name',
  'goalie_name',
  'qb_player_name',
  'kicker_player_name',
] as const;

export type DiscoveryRankMode = 'positive_edge' | 'projected_value';

export type DiscoveryGroupConfig = {
  /** Section heading in the discovery strip. */
  title: string;
  /** Key into the sport predictions payload. */
  responseKey: string;
  mode: DiscoveryRankMode;
  /** Edge field for positive_edge mode (default `edge`). */
  edgeKey?: string;
  /** Numeric field for projected_value mode (e.g. `projected_hits`). */
  valueKey?: string;
  /** Person name field on the row. */
  nameKey: string;
  projectedKey?: string;
  lineKey?: string;
  pickKey?: string;
  limit?: number;
};

const DEFAULT_LIMIT = 3;

export function asNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

/** First non-empty person-name field on a projection row. */
export function rowPersonName(row: Record<string, unknown>): string {
  for (const key of PERSON_NAME_KEYS) {
    const v = row[key];
    if (v !== null && v !== undefined && String(v).trim() !== '') {
      return String(v).trim();
    }
  }
  return '';
}

export function rowMatchesPlayerSearch(
  row: Record<string, unknown>,
  query: string
): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const name = rowPersonName(row).toLowerCase();
  if (name.includes(q)) return true;
  // Also match the configured primary name key if present but empty in PERSON_NAME_KEYS miss
  for (const key of PERSON_NAME_KEYS) {
    const v = row[key];
    if (v != null && String(v).toLowerCase().includes(q)) return true;
  }
  return false;
}

export function selectTopPositiveEdge(
  rows: Array<Record<string, unknown>>,
  edgeKey = 'edge',
  limit = DEFAULT_LIMIT
): Array<Record<string, unknown>> {
  return rows
    .map((row) => ({ row, edge: asNumber(row[edgeKey]) }))
    .filter((x): x is { row: Record<string, unknown>; edge: number } => x.edge != null && x.edge > 0)
    .sort((a, b) => b.edge - a.edge)
    .slice(0, limit)
    .map((x) => x.row);
}

export function selectTopByNumericField(
  rows: Array<Record<string, unknown>>,
  valueKey: string,
  limit = DEFAULT_LIMIT
): Array<Record<string, unknown>> {
  return rows
    .map((row) => ({ row, value: asNumber(row[valueKey]) }))
    .filter((x): x is { row: Record<string, unknown>; value: number } => x.value != null)
    .sort((a, b) => b.value - a.value)
    .slice(0, limit)
    .map((x) => x.row);
}

export function selectDiscoveryRows(
  rows: Array<Record<string, unknown>>,
  group: DiscoveryGroupConfig
): Array<Record<string, unknown>> {
  const limit = group.limit ?? DEFAULT_LIMIT;
  if (group.mode === 'positive_edge') {
    return selectTopPositiveEdge(rows, group.edgeKey ?? 'edge', limit);
  }
  const valueKey = group.valueKey;
  if (!valueKey) return [];
  return selectTopByNumericField(rows, valueKey, limit);
}

export function buildDiscoverySections(
  data: Record<string, Array<Record<string, unknown>>> | null | undefined,
  groups: DiscoveryGroupConfig[]
): Array<DiscoveryGroupConfig & { rows: Array<Record<string, unknown>> }> {
  if (!data || groups.length === 0) return [];
  return groups
    .map((group) => {
      const all = data[group.responseKey] ?? [];
      return { ...group, rows: selectDiscoveryRows(all, group) };
    })
    .filter((g) => g.rows.length > 0);
}
