import { parseApiTimestamp } from '@/lib/formatting';

type Row = Record<string, unknown>;

const TIME_KEYS = ['game_time', 'game_time_et', 'commence_time', 'start_time'] as const;

export function gameTimeFromRow(row: Row): Date | null {
  for (const key of TIME_KEYS) {
    const parsed = parseApiTimestamp(row[key] as string | Date | null | undefined);
    if (parsed) return parsed;
  }
  return null;
}

export function formatGameProjectionTime(row: Row): string | null {
  const dt = gameTimeFromRow(row);
  if (!dt) return null;
  return dt.toLocaleTimeString(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  });
}

function matchupSortKey(row: Row): string {
  const away = String(row.away_team ?? row.away_team_name ?? '').trim();
  const home = String(row.home_team ?? row.home_team_name ?? '').trim();
  return `${away}@${home}`.toLowerCase();
}

export function sortGameProjectionRows<T extends Row>(rows: T[]): T[] {
  return [...rows].sort((a, b) => {
    const ta = gameTimeFromRow(a)?.getTime();
    const tb = gameTimeFromRow(b)?.getTime();
    if (ta == null && tb == null) return matchupSortKey(a).localeCompare(matchupSortKey(b));
    if (ta == null) return 1;
    if (tb == null) return -1;
    if (ta !== tb) return ta - tb;
    return matchupSortKey(a).localeCompare(matchupSortKey(b));
  });
}
