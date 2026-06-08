import {
  buildTradeAssetsFromBuilder,
  buildTradeAssetsFromRecommendation,
  resolveSleeperPlayerId,
} from '@/lib/fantasy-trade-proposal';

describe('fantasy-trade-proposal', () => {
  describe('resolveSleeperPlayerId', () => {
    it('prefers id over player_id', () => {
      expect(resolveSleeperPlayerId({ id: 1234, player_id: '9999' })).toBe('1234');
    });

    it('falls back to player_id', () => {
      expect(resolveSleeperPlayerId({ player_id: '4046' })).toBe('4046');
    });

    it('returns null for missing or invalid ids', () => {
      expect(resolveSleeperPlayerId({})).toBeNull();
      expect(resolveSleeperPlayerId({ id: 0 })).toBeNull();
      expect(resolveSleeperPlayerId({ id: '' })).toBeNull();
    });
  });

  describe('buildTradeAssetsFromRecommendation', () => {
    it('maps recommendation players to string sleeper ids', () => {
      const assets = buildTradeAssetsFromRecommendation({
        players: [
          { id: 4046, name: 'Player A' },
          { player_id: '8134', name: 'Player B' },
          { id: 0, name: 'Invalid' },
        ],
        picks: [2026],
        faab: 25,
      });

      expect(assets).toEqual({
        players: ['4046', '8134'],
        picks: [2026],
        faab: 25,
      });
    });

    it('defaults picks and faab when omitted', () => {
      expect(
        buildTradeAssetsFromRecommendation({
          players: [{ id: '123' }],
        })
      ).toEqual({
        players: ['123'],
        picks: [],
        faab: 0,
      });
    });
  });

  describe('buildTradeAssetsFromBuilder', () => {
    it('stringifies numeric player ids from the manual builder', () => {
      expect(
        buildTradeAssetsFromBuilder({
          players: [4046, 8134],
          picks: [],
          faab: 0,
        })
      ).toEqual({
        players: ['4046', '8134'],
        picks: [],
        faab: 0,
      });
    });
  });
});
