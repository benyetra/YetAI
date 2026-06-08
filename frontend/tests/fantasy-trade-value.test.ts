import {
  QB_PREMIUM_SUPERFLEX,
  calculateDeterministicTradeValue,
} from '@/lib/fantasy-trade-value';
import type { LeagueRules } from '@/lib/fantasy-league-rules';

const basePlayer = {
  id: 'qb-test',
  position: 'QB',
  age: 27,
  team: 'KC',
};

const standardRules: LeagueRules = {
  league_id: 'lg-1',
  league_name: 'Standard',
  platform: 'sleeper',
  season: 2025,
  league_type: '12-Team League',
  team_count: 12,
  scoring_type: 'ppr',
  roster_settings: {
    total_spots: 16,
    starting_spots: 9,
    bench_spots: 7,
    positions: { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, K: 1, DEF: 1 },
    position_requirements: [],
  },
  scoring_settings: {
    type: 'ppr',
    passing: { touchdowns: 4, yards_per_point: 0.04, interceptions: -2 },
    rushing: { touchdowns: 6, yards_per_point: 0.1, fumbles: -2 },
    receiving: { touchdowns: 6, yards_per_point: 0.1, receptions: 1 },
    special_scoring: [],
    raw_settings: {},
  },
  features: {
    trades_enabled: true,
    waivers_enabled: true,
    playoffs: { teams: 6, weeks: 3 },
  },
  ai_context: {
    prioritize_volume: true,
    rb_premium: false,
    flex_strategy: true,
    superflex: false,
    position_scarcity: {},
  },
};

describe('fantasy-trade-value', () => {
  it('boosts QB value in superflex leagues', () => {
    const standard = calculateDeterministicTradeValue(basePlayer, standardRules);
    const superflex = calculateDeterministicTradeValue(basePlayer, {
      ...standardRules,
      ai_context: { ...standardRules.ai_context, superflex: true },
    });
    expect(superflex).toBeGreaterThan(standard);
    expect(superflex).toBe(Math.round(standard * QB_PREMIUM_SUPERFLEX * 10) / 10);
  });

  it('boosts TE value in large leagues without explicit premium', () => {
    const tePlayer = { ...basePlayer, id: 'te-test', position: 'TE' };
    const smallLeague = calculateDeterministicTradeValue(tePlayer, {
      ...standardRules,
      team_count: 10,
    });
    const largeLeague = calculateDeterministicTradeValue(tePlayer, standardRules);
    expect(largeLeague).toBeGreaterThan(smallLeague);
  });
});
