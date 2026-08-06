import {
  formatDraftPlayer,
  h2hShortName,
  isDraftPending,
  isPlaceholderPlayerId,
  resolveRecordMatchup,
  vaultNameFitClass,
  type VaultSnapshot,
} from '../../src/lib/vault';

describe('vault helpers', () => {
  it('h2hShortName uses initials for multi-word names', () => {
    expect(h2hShortName('Mike Hard')).toBe('MH');
    expect(h2hShortName('The Tyler Wong')).toBe('TTW');
  });

  it('h2hShortName truncates single tokens', () => {
    expect(h2hShortName('BYETRA')).toBe('BYET');
    expect(h2hShortName('Bob')).toBe('Bob');
  });

  it('vaultNameFitClass scales long unbroken handles instead of mid-word breaks', () => {
    expect(vaultNameFitClass('Bob')).toBe('vault-name');
    expect(vaultNameFitClass('Remdick')).toBe('vault-name');
    expect(vaultNameFitClass('bearjew23')).toBe('vault-name is-compact');
    expect(vaultNameFitClass('eddieprado89')).toBe('vault-name is-tight');
    expect(vaultNameFitClass('thetylerwong')).toBe('vault-name is-tight');
    expect(vaultNameFitClass('superlongusernamehere')).toBe('vault-name is-micro');
    expect(vaultNameFitClass('Mike Hard')).toBe('vault-name');
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

  it('resolveRecordMatchup finds both managers from season scoreboard', () => {
    const snap = {
      managers: [
        { id: 1, slug: 'alice', display_name: 'Alice' },
        { id: 2, slug: 'bob', display_name: 'Bob' },
      ],
      seasons: [
        {
          season: 2022,
          teams: [
            { id: 10, manager_id: 1 },
            { id: 11, manager_id: 2 },
          ],
          matchups: [
            {
              week: 10,
              team_a_id: 10,
              team_b_id: 11,
              team_a_score: 97.84,
              team_b_score: 97.9,
            },
          ],
        },
      ],
    } as unknown as VaultSnapshot;

    const parties = resolveRecordMatchup(snap, {
      record_key: 'closest_game',
      scope: 'all_time',
      season: null,
      manager_id: null,
      team_id: null,
      value: 0.06,
      context: { season: 2022, week: 10, team_a_score: 97.84, team_b_score: 97.9 },
    });
    expect(parties?.managerA.display_name).toBe('Alice');
    expect(parties?.managerB.display_name).toBe('Bob');
  });
});
