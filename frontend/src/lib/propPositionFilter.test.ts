import { filterRowsByPosition } from '@/lib/propPositionFilter';

describe('filterRowsByPosition', () => {
  const rows = [
    { player_name: 'A', position: 'WR' },
    { player_name: 'B', position: 'RB' },
    { player_name: 'C', position: 'TE' },
  ];

  it('returns all rows when filter is All', () => {
    expect(filterRowsByPosition(rows, 'position', 'All')).toHaveLength(3);
  });

  it('filters to a single position', () => {
    expect(filterRowsByPosition(rows, 'position', 'WR')).toEqual([
      { player_name: 'A', position: 'WR' },
    ]);
  });
});
