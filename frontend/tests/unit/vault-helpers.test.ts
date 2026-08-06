import { formatDraftPlayer, h2hShortName, isDraftPending, isPlaceholderPlayerId } from '../../src/lib/vault';

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

  it('treats ESPN pre-draft -1 as empty player', () => {
    expect(isPlaceholderPlayerId('-1')).toBe(true);
    expect(formatDraftPlayer({ player_id: '-1' })).toBe('—');
    expect(
      isDraftPending({
        status: 'pending',
        picks_made: 0,
        picks: [{ player_id: null }, { player_id: null }],
      }),
    ).toBe(true);
  });
});
