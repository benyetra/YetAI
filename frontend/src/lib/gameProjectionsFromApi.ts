import type { GameProjectionsVariant } from '@/components/yetai/MlbGameProjectionsGrid';
import { mapNhlTeamTotalsRows } from './mapNhlGameProjections';
import { mergeSpreadTotalsGameProjections } from './mergeSpreadTotalsGameProjections';

type Row = Record<string, unknown>;
type ApiData = Record<string, Array<Record<string, unknown>>> | null;

export function gameProjectionRows(variant: GameProjectionsVariant, data: ApiData): Row[] {
  if (!data) return [];

  switch (variant) {
    case 'mlb':
      return (data.game_projections as Row[]) ?? [];
    case 'nba':
    case 'wnba':
      return mergeSpreadTotalsGameProjections(
        (data.spreads as Row[]) ?? [],
        (data.totals as Row[]) ?? [],
      );
    case 'nhl':
      return mapNhlTeamTotalsRows((data.team_totals as Row[]) ?? []);
    case 'nfl':
      return [];
    default:
      return [];
  }
}
