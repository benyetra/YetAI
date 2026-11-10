import { NFL_RECV_YDS_COLUMNS } from '@/lib/propProjectionDisplay';

describe('NFL_RECV_YDS_COLUMNS', () => {
  it('labels Pos + Model / Market / Edge / Pick', () => {
    expect(NFL_RECV_YDS_COLUMNS.map((c) => c.label)).toEqual([
      'Player',
      'Pos',
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

  it('binds Model to predicted_receiving_yards and Market to ou_line', () => {
    expect(NFL_RECV_YDS_COLUMNS.find((c) => c.label === 'Model')?.key).toBe(
      'predicted_receiving_yards',
    );
    expect(NFL_RECV_YDS_COLUMNS.find((c) => c.label === 'Market')?.key).toBe(
      'ou_line',
    );
    expect(NFL_RECV_YDS_COLUMNS.find((c) => c.label === 'Pos')?.key).toBe(
      'position',
    );
  });
});
