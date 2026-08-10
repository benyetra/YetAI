import { gameProjectionRows } from '@/lib/gameProjectionsFromApi';

describe('gameProjectionRows nfl', () => {
  it('merges spreads and totals into unified game cards', () => {
    const rows = gameProjectionRows('nfl', {
      spreads: [
        {
          home_team_name: 'Kansas City Chiefs',
          away_team_name: 'Baltimore Ravens',
          home_win_prob: 0.62,
          projected_margin: 3.5,
          market_spread_home: -3.0,
          edge: 0.5,
          recommendation: 'HOME',
          confidence_score: 72,
          game_time: '2026-09-10T00:20:00Z',
        },
      ],
      totals: [
        {
          home_team_name: 'Kansas City Chiefs',
          away_team_name: 'Baltimore Ravens',
          projected_total: 47.5,
          home_projected_score: 25.5,
          away_projected_score: 22.0,
          market_total: 48.5,
          edge: -1.0,
          recommendation: 'UNDER',
        },
      ],
    });

    expect(rows).toHaveLength(1);
    expect(rows[0].projected_total).toBe(47.5);
    expect(rows[0].home_team).toBe('Kansas City Chiefs');
    expect(rows[0].away_team).toBe('Baltimore Ravens');
    expect(rows[0].home_win_prob).toBe(0.62);
    expect(rows[0].projected_margin).toBe(3.5);
    expect(rows[0].market_spread).toBe(-3.0);
    expect(rows[0].spread_edge).toBe(0.5);
    expect(rows[0].spread_recommendation).toBe('HOME');
    expect(rows[0].home_projected_runs).toBe(25.5);
    expect(rows[0].away_projected_runs).toBe(22.0);
    expect(rows[0].market_total).toBe(48.5);
    expect(rows[0].edge_vs_market_total).toBe(-1.0);
    expect(rows[0].total_recommendation).toBe('UNDER');
    expect(rows[0].model_confidence).toBe(72);
  });

  it('returns empty array when data is null', () => {
    expect(gameProjectionRows('nfl', null)).toEqual([]);
  });
});
