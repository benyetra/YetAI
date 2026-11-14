import { mapNhlTeamTotalsRows } from '@/lib/mapNhlGameProjections';
import { mergeSpreadTotalsGameProjections } from '@/lib/mergeSpreadTotalsGameProjections';
import { resultBadge, withPastResultColumns } from '@/lib/propProjectionDisplay';

const base = [{ key: 'player_name', label: 'Player' }];

describe('withPastResultColumns', () => {
  it('appends Actual + Result when rows carry a result', () => {
    const cols = withPastResultColumns(base, [{ result: 'hit' }]);
    expect(cols.map((c) => c.key)).toEqual(['player_name', 'actual', 'result']);
  });

  it('does not duplicate an existing actual_* column (MLB)', () => {
    const cols = withPastResultColumns([...base, { key: 'actual_strikeouts', label: 'Actual K' }], [
      { result: 'miss' },
    ]);
    expect(cols.map((c) => c.key)).toEqual(['player_name', 'actual_strikeouts', 'result']);
  });

  it('leaves groups the grader does not cover alone', () => {
    expect(withPastResultColumns(base, [{ id: 1 }])).toBe(base);
    expect(withPastResultColumns(base, undefined)).toBe(base);
  });
});

describe('resultBadge', () => {
  it('labels every result and keeps DNP distinct from Ungraded', () => {
    expect(['hit', 'miss', 'push', 'no_play', 'dnp', 'ungraded'].map((r) => resultBadge(r).label)).toEqual([
      'Hit',
      'Miss',
      'Push',
      'No play',
      'DNP',
      'Ungraded',
    ]);
    expect(resultBadge('dnp').className).not.toBe(resultBadge('ungraded').className);
    expect(resultBadge(undefined).label).toBe('Ungraded');
  });
});

describe('game mappers keep the per-row result', () => {
  it('spread/totals merge exposes spread_result and total_result', () => {
    const [row] = mergeSpreadTotalsGameProjections(
      [{ id: 1, home_team_name: 'A', away_team_name: 'B', result: 'miss' }],
      [{ id: 2, home_team_name: 'A', away_team_name: 'B', result: 'hit' }],
    );
    expect(row.spread_result).toBe('miss');
    expect(row.total_result).toBe('hit');
  });

  it('NHL mapper exposes total_result', () => {
    const [row] = mapNhlTeamTotalsRows([{ id: 3, result: 'push' }]);
    expect(row.total_result).toBe('push');
  });
});
