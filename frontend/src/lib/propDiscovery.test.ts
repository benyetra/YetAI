import {
  buildDiscoverySections,
  rowMatchesPlayerSearch,
  rowPersonName,
  selectTopByNumericField,
  selectTopPositiveEdge,
} from '@/lib/propDiscovery';

describe('rowPersonName / search', () => {
  it('reads the first person-name field', () => {
    expect(rowPersonName({ player_name: 'A’ja Wilson' })).toBe('A’ja Wilson');
    expect(rowPersonName({ pitcher_name: 'Gerrit Cole' })).toBe('Gerrit Cole');
    expect(rowPersonName({})).toBe('');
  });

  it('matches case-insensitive substrings', () => {
    const row = { player_name: 'A’ja Wilson' };
    expect(rowMatchesPlayerSearch(row, 'wil')).toBe(true);
    expect(rowMatchesPlayerSearch(row, 'XYZ')).toBe(false);
    expect(rowMatchesPlayerSearch(row, '  ')).toBe(true);
  });
});

describe('selectTopPositiveEdge', () => {
  it('keeps only positive edges and ranks highest first', () => {
    const rows = [
      { player_name: 'A', edge: 1.2, recommendation: 'OVER' },
      { player_name: 'B', edge: -2.0, recommendation: 'OVER' },
      { player_name: 'C', edge: 3.5, recommendation: 'OVER' },
      { player_name: 'D', edge: 0, recommendation: 'OVER' },
      { player_name: 'E', edge: 2.1, recommendation: 'OVER' },
      { player_name: 'F', edge: 0.5, recommendation: 'OVER' },
    ];
    const top = selectTopPositiveEdge(rows, 'edge', 3);
    expect(top.map((r) => r.player_name)).toEqual(['C', 'E', 'A']);
  });

  it('supports alternate edge keys', () => {
    const rows = [
      { pitcher_name: 'A', k_edge: 0.8, recommendation: 'OVER' },
      { pitcher_name: 'B', k_edge: 2.2, recommendation: 'OVER' },
      { pitcher_name: 'C', k_edge: -1, recommendation: 'OVER' },
    ];
    const top = selectTopPositiveEdge(rows, 'k_edge', 3);
    expect(top.map((r) => r.pitcher_name)).toEqual(['B', 'A']);
  });
});

describe('selectTopByNumericField', () => {
  it('ranks projected hits descending', () => {
    const rows = [
      { batter_name: 'A', projected_hits: 1 },
      { batter_name: 'B', projected_hits: 3 },
      { batter_name: 'C', projected_hits: 2 },
    ];
    const top = selectTopByNumericField(rows, 'projected_hits', 2);
    expect(top.map((r) => r.batter_name)).toEqual(['B', 'C']);
  });
});

describe('buildDiscoverySections', () => {
  it('omits empty groups', () => {
    const sections = buildDiscoverySections(
      {
        points: [{ player_name: 'A', edge: -1, recommendation: 'OVER' }],
        assists: [
          { player_name: 'B', edge: 2.0, recommendation: 'OVER' },
          { player_name: 'C', edge: 1.0, recommendation: 'OVER' },
        ],
      },
      [
        {
          title: 'Points',
          responseKey: 'points',
          mode: 'positive_edge',
          nameKey: 'player_name',
        },
        {
          title: 'Assists',
          responseKey: 'assists',
          mode: 'positive_edge',
          nameKey: 'player_name',
        },
      ]
    );
    expect(sections).toHaveLength(1);
    expect(sections[0].title).toBe('Assists');
    expect(sections[0].rows).toHaveLength(2);
  });
});

describe('selectTopPositiveEdge: explicit picks only', () => {
  it('excludes positive-edge rows with no pick or with pick_withheld', () => {
    const rows = [
      { player_name: 'NoPick', edge: 9, recommendation: null },
      { player_name: 'NoPlay', edge: 8, recommendation: 'NO_PLAY' },
      { player_name: 'Withheld', edge: 7, recommendation: 'OVER', pick_withheld: 'unproven_record' },
      { player_name: 'Real', edge: 1, recommendation: 'UNDER' },
    ];
    expect(selectTopPositiveEdge(rows).map((r) => r.player_name)).toEqual(['Real']);
  });

  it('ranks by edge, null-edge rows never ahead of rows with an edge', () => {
    const rows = [
      { player_name: 'Null', edge: null, recommendation: 'OVER' },
      { player_name: 'Low', edge: 0.5, recommendation: 'OVER' },
      { player_name: 'High', edge: 2, recommendation: 'OVER' },
    ];
    expect(selectTopPositiveEdge(rows).map((r) => r.player_name)).toEqual(['High', 'Low']);
  });

  it('honours a custom pickKey (MLB yetai_pick)', () => {
    const rows = [{ pitcher_name: 'X', k_edge: 1, yetai_pick: null, recommendation: 'OVER' }];
    expect(selectTopPositiveEdge(rows, 'k_edge', 3, 'yetai_pick')).toEqual([]);
  });
});
