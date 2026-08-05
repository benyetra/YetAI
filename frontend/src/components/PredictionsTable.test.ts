import {
  comparePredictionRows,
  personNameSortKey,
} from '@/components/PredictionsTable';

describe('personNameSortKey', () => {
  it('uses last token as primary sort key', () => {
    expect(personNameSortKey('Aaron Judge')).toBe('judge aaron');
    expect(personNameSortKey('Shohei Ohtani')).toBe('ohtani shohei');
  });

  it('ignores generational suffixes when picking last name', () => {
    expect(personNameSortKey('Ken Griffey Jr.')).toBe('griffey ken jr.');
    expect(personNameSortKey('Henry Aaron III')).toBe('aaron henry iii');
  });

  it('handles single-token and empty names', () => {
    expect(personNameSortKey('Nadal')).toBe('nadal');
    expect(personNameSortKey('')).toBe('');
    expect(personNameSortKey(null)).toBe('');
  });
});

describe('comparePredictionRows person names', () => {
  it('sorts player_name by last name ascending', () => {
    const a = { player_name: 'Aaron Judge' };
    const b = { player_name: 'Mookie Betts' };
    expect(comparePredictionRows(a, b, 'player_name', 'asc')).toBeGreaterThan(0);
    expect(comparePredictionRows(b, a, 'player_name', 'asc')).toBeLessThan(0);
  });

  it('does not last-name-sort team columns', () => {
    const a = { team_name: 'New York Yankees' };
    const b = { team_name: 'Boston Red Sox' };
    // Lexicographic on full string: "boston..." < "new..."
    expect(comparePredictionRows(a, b, 'team_name', 'asc')).toBeGreaterThan(0);
  });
});
