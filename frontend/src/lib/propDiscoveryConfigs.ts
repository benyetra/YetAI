import type { DiscoveryGroupConfig } from '@/lib/propDiscovery';

const basketballEdge = (
  title: string,
  responseKey: string,
  projectedKey: string,
  lineKey = 'fanduel_line'
): DiscoveryGroupConfig => ({
  title,
  responseKey,
  mode: 'positive_edge',
  edgeKey: 'edge',
  nameKey: 'player_name',
  projectedKey,
  lineKey,
  pickKey: 'recommendation',
});

export const NBA_DISCOVERY_GROUPS: DiscoveryGroupConfig[] = [
  basketballEdge('Points', 'points', 'projected_points'),
  basketballEdge('Assists', 'assists', 'projected_assists'),
  basketballEdge('Rebounds', 'rebounds', 'projected_rebounds'),
  basketballEdge('Three-Pointers', 'three_point', 'projected_three_pt_made'),
  basketballEdge('Steals', 'steals', 'projected_steals'),
  basketballEdge('Blocks', 'blocks', 'projected_blocks'),
  basketballEdge('PRA', 'pra', 'projected_pra'),
];

export const WNBA_DISCOVERY_GROUPS: DiscoveryGroupConfig[] = [
  basketballEdge('Points', 'points', 'projected_points', 'market_line'),
  basketballEdge('Assists', 'assists', 'projected_assists', 'market_line'),
  basketballEdge('Rebounds', 'rebounds', 'projected_rebounds', 'market_line'),
];

export const MLB_DISCOVERY_GROUPS: DiscoveryGroupConfig[] = [
  {
    title: 'Strikeouts',
    responseKey: 'strikeout_projections',
    mode: 'positive_edge',
    edgeKey: 'k_edge',
    nameKey: 'pitcher_name',
    projectedKey: 'projected_strikeouts',
    lineKey: 'fanduel_line',
    pickKey: 'yetai_pick',
  },
  {
    title: 'Best hit chances',
    responseKey: 'projected_hits',
    mode: 'projected_value',
    valueKey: 'projected_hits',
    nameKey: 'batter_name',
    projectedKey: 'projected_hits',
  },
];
