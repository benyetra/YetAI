import type { VaultSnapshot } from '../../src/lib/vault';
import {
  buildDraftIntrigue,
  buildLuckCallouts,
  buildRivalryCards,
  buildSeasonBeats,
  buildShareSeasonCard,
  buildThrowbackMoment,
  buildTitleDroughts,
  buildTitleStreaks,
  dynastyCellNote,
  managerEpithet,
} from '../../src/lib/vault-intrigue';

function mgr(
  id: number,
  name: string,
  opts: Partial<VaultSnapshot['managers'][number]> = {},
): VaultSnapshot['managers'][number] {
  return {
    id,
    slug: name.toLowerCase(),
    display_name: name,
    canonical_name: name,
    aliases: [],
    first_season: 2021,
    last_season: 2024,
    is_active: true,
    ...opts,
  };
}

const alice = mgr(1, 'Alice');
const bob = mgr(2, 'Bob');
const cara = mgr(3, 'Cara');

const snap = {
  slug: 'test-league',
  display_name: "Mike's Hard Fantasy Football League",
  tagline: null,
  first_season: 2021,
  latest_season: 2024,
  last_place_label: 'Sacko',
  generated_at: '2026-01-01T00:00:00Z',
  reigning_champion: { ...cara, season: 2024 },
  managers: [alice, bob, cara],
  manager_careers: {
    '1': { wins: 40, losses: 20, ties: 0, points_for: 9000, titles: 2 },
    '2': { wins: 28, losses: 32, ties: 0, points_for: 8200, titles: 0 },
    '3': { wins: 35, losses: 25, ties: 0, points_for: 8600, titles: 2 },
  },
  seasons: [
    {
      season: 2023,
      team_count: 3,
      playoff_teams: 2,
      regular_season_weeks: 14,
      champion: alice,
      runner_up: bob,
      last_place: cara,
      teams: [
        {
          id: 10,
          manager_id: 1,
          team_name: 'Aces',
          avatar_url: null,
          wins: 10,
          losses: 4,
          ties: 0,
          points_for: 1600,
          points_against: 1400,
          final_rank: 1,
          playoff_seed: 1,
          all_play_wins: 20,
          all_play_losses: 8,
          luck_differential: 1.2,
          moves: 5,
        },
        {
          id: 11,
          manager_id: 2,
          team_name: 'Bears',
          avatar_url: null,
          wins: 7,
          losses: 7,
          ties: 0,
          points_for: 1500,
          points_against: 1500,
          final_rank: 2,
          playoff_seed: 2,
          all_play_wins: 18,
          all_play_losses: 10,
          luck_differential: -1.5,
          moves: 8,
        },
        {
          id: 12,
          manager_id: 3,
          team_name: 'Cats',
          avatar_url: null,
          wins: 4,
          losses: 10,
          ties: 0,
          points_for: 1300,
          points_against: 1600,
          final_rank: 3,
          playoff_seed: null,
          all_play_wins: 22,
          all_play_losses: 6,
          luck_differential: -2.1,
          moves: 3,
        },
      ],
      matchups: [
        {
          week: 5,
          is_playoff: false,
          team_a_id: 10,
          team_b_id: 11,
          team_a_score: 100.1,
          team_b_score: 99.9,
          winner_team_id: 10,
          margin: 0.2,
        },
        {
          week: 5,
          is_playoff: false,
          team_a_id: 12,
          team_b_id: 11,
          team_a_score: 140,
          team_b_score: 90,
          winner_team_id: 12,
          margin: 50,
        },
      ],
      drafts: [
        {
          draft_type: 'snake',
          status: 'complete',
          rounds: 2,
          picks_made: 3,
          picks: [
            {
              round: 1,
              pick_no: 1,
              draft_slot: 1,
              team_id: 12,
              player_id: '1',
              player_name: 'Star RB',
              player_position: 'RB',
              player_nfl_team: 'SF',
              is_keeper: null,
              auction_amount: null,
            },
            {
              round: 1,
              pick_no: 2,
              draft_slot: 2,
              team_id: 11,
              player_id: '2',
              player_name: 'Mid WR',
              player_position: 'WR',
              player_nfl_team: 'DAL',
              is_keeper: null,
              auction_amount: null,
            },
            {
              round: 1,
              pick_no: 3,
              draft_slot: 3,
              team_id: 10,
              player_id: '3',
              player_name: 'Late QB',
              player_position: 'QB',
              player_nfl_team: 'BUF',
              is_keeper: null,
              auction_amount: null,
            },
          ],
        },
      ],
      transaction_count: 0,
    },
    {
      season: 2024,
      team_count: 3,
      playoff_teams: 2,
      regular_season_weeks: 14,
      champion: cara,
      runner_up: alice,
      last_place: bob,
      teams: [
        {
          id: 20,
          manager_id: 3,
          team_name: 'Cats II',
          avatar_url: null,
          wins: 11,
          losses: 3,
          ties: 0,
          points_for: 1700,
          points_against: 1400,
          final_rank: 1,
          playoff_seed: 1,
          all_play_wins: 16,
          all_play_losses: 12,
          luck_differential: 2.4,
          moves: 4,
        },
        {
          id: 21,
          manager_id: 1,
          team_name: 'Aces II',
          avatar_url: null,
          wins: 8,
          losses: 6,
          ties: 0,
          points_for: 1550,
          points_against: 1500,
          final_rank: 2,
          playoff_seed: 2,
          all_play_wins: 17,
          all_play_losses: 11,
          luck_differential: 0.1,
          moves: 6,
        },
        {
          id: 22,
          manager_id: 2,
          team_name: 'Bears II',
          avatar_url: null,
          wins: 3,
          losses: 11,
          ties: 0,
          points_for: 1200,
          points_against: 1700,
          final_rank: 3,
          playoff_seed: null,
          all_play_wins: 14,
          all_play_losses: 14,
          luck_differential: -1.1,
          moves: 9,
        },
      ],
      matchups: [
        {
          week: 3,
          is_playoff: false,
          team_a_id: 20,
          team_b_id: 21,
          team_a_score: 112,
          team_b_score: 110.5,
          winner_team_id: 20,
          margin: 1.5,
        },
      ],
      drafts: [],
      transaction_count: 0,
    },
  ],
  records: [],
  h2h: {
    '1': {
      '2': { wins: 8, losses: 2, ties: 0 },
      '3': { wins: 5, losses: 5, ties: 0 },
    },
    '2': {
      '1': { wins: 2, losses: 8, ties: 0 },
      '3': { wins: 4, losses: 4, ties: 1 },
    },
    '3': {
      '1': { wins: 5, losses: 5, ties: 0 },
      '2': { wins: 4, losses: 4, ties: 1 },
    },
  },
  dynasty_timeline: [
    { season: 2021, champion: alice },
    { season: 2022, champion: alice },
    { season: 2023, champion: alice },
    { season: 2024, champion: cara },
  ],
} as unknown as VaultSnapshot;

describe('vault intrigue', () => {
  it('builds rivalry cards for lopsided and dead-even series', () => {
    const cards = buildRivalryCards(snap);
    expect(cards.length).toBeGreaterThanOrEqual(2);
    expect(cards.some((c) => c.kind === 'lopsided')).toBe(true);
    expect(cards.some((c) => c.kind === 'dead_even' || c.kind === 'blood_feud')).toBe(true);
  });

  it('builds season story beats from matchups and luck', () => {
    const beats = buildSeasonBeats(snap, snap.seasons[0]);
    expect(beats.map((b) => b.key)).toEqual(
      expect.arrayContaining(['closest', 'combined', 'blowout', 'almost']),
    );
  });

  it('surfaces lucky and unlucky karma callouts', () => {
    const karma = buildLuckCallouts(snap);
    expect(karma.some((k) => k.kind === 'lucky')).toBe(true);
    expect(karma.some((k) => k.kind === 'unlucky')).toBe(true);
  });

  it('flags first-overall regret and late-round glory', () => {
    const items = buildDraftIntrigue(snap, snap.seasons[0]);
    expect(items.some((i) => i.kind === 'regret')).toBe(true);
    expect(items.some((i) => i.kind === 'glory')).toBe(true);
  });

  it('detects title streaks and droughts', () => {
    const streaks = buildTitleStreaks(snap);
    expect(streaks[0]?.length).toBe(3);
    expect(streaks[0]?.label).toBe('3-peat');
    expect(dynastyCellNote(snap, 2023, alice.id)).toBe('3-peat');

    const droughts = buildTitleDroughts(snap);
    expect(droughts.some((d) => d.manager.id === bob.id)).toBe(true);
  });

  it('rotates a throwback moment and builds share cards', () => {
    const moment = buildThrowbackMoment(snap, new Date('2026-02-01T12:00:00Z'));
    expect(moment).not.toBeNull();
    expect(moment?.scoreLabel).toMatch(/–/);

    const card = buildShareSeasonCard(snap, snap.seasons[1], 'test-league');
    expect(card?.championName).toBe('Cara');
    expect(card?.href).toBe('/vault/test-league/seasons/2024');
  });

  it('assigns witty manager epithets', () => {
    expect(managerEpithet(snap, alice.id)?.epithet).toMatch(/Dynasty|Repeat|Assassin|Wonder/);
    expect(managerEpithet(snap, bob.id)?.epithet).toMatch(/Nearly|Victim|Specialist|Contender/);
  });
});
