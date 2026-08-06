import { formatDraftPlayer, h2hShortName } from '../../src/lib/vault';

describe('vault helpers', () => {
  it('h2hShortName uses initials for multi-word names', () => {
    expect(h2hShortName('Mike Hard')).toBe('MH');
    expect(h2hShortName('The Tyler Wong')).toBe('TTW');
  });

  it('h2hShortName truncates single tokens', () => {
    expect(h2hShortName('BYETRA')).toBe('BYET');
    expect(h2hShortName('Bob')).toBe('Bob');
  });

  it('formatDraftPlayer prefers name + meta over raw id', () => {
    expect(
      formatDraftPlayer({
        player_name: 'Saquon Barkley',
        player_position: 'RB',
        player_nfl_team: 'PHI',
        player_id: '4866',
      }),
    ).toBe('Saquon Barkley — RB · PHI');
    expect(formatDraftPlayer({ player_id: '4866' })).toBe('4866');
    expect(formatDraftPlayer({})).toBe('—');
  });
});
