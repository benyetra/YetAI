import type { GameProjectionsVariant } from '@/components/yetai/MlbGameProjectionsGrid';
import { sortGameProjectionRows } from './gameProjectionSchedule';
import { mapNhlTeamTotalsRows } from './mapNhlGameProjections';
import { mergeSpreadTotalsGameProjections } from './mergeSpreadTotalsGameProjections';

type Row = Record<string, unknown>;
type ApiData = Record<string, Array<Record<string, unknown>>> | null;

export function gameProjectionRows(variant: GameProjectionsVariant, data: ApiData): Row[] {
  if (!data) return [];

  let rows: Row[];
  switch (variant) {
    case 'mlb':
      rows = (data.game_projections as Row[]) ?? [];
      break;
    case 'nba':
    case 'wnba':
      rows = mergeSpreadTotalsGameProjections(
        (data.spreads as Row[]) ?? [],
        (data.totals as Row[]) ?? [],
      );
      break;
    case 'nhl':
      rows = mapNhlTeamTotalsRows((data.team_totals as Row[]) ?? []);
      break;
    case 'nfl':
      rows = mergeSpreadTotalsGameProjections(
        (data.spreads as Row[]) ?? [],
        (data.totals as Row[]) ?? [],
      );
      break;
    default:
      rows = [];
  }

  return sortGameProjectionRows(rows);
}
