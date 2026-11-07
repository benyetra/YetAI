import { NFL_QB_COLUMNS } from '@/lib/propProjectionDisplay';

describe('NFL_QB_COLUMNS', () => {
  it('labels Model / Market / Edge / Pick like the ATD board', () => {
    expect(NFL_QB_COLUMNS.map((c) => c.label)).toEqual([
      'QB',
      'Team',
      'Opponent Team',
      'Model',
      'Market',
      'Edge',
      'Pick',
      'Conf',
      'News',
    ]);
  });

  it('binds Model to predicted yards and Market to ou_line', () => {
    expect(NFL_QB_COLUMNS.find((c) => c.label === 'Model')?.key).toBe(
      'predicted_passing_yards',
    );
    expect(NFL_QB_COLUMNS.find((c) => c.label === 'Market')?.key).toBe(
      'ou_line',
    );
  });
});
