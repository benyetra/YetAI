import {
  ANYTIME_TD_COLUMNS,
  formatAnytimeTdEdge,
  formatMarketOdds,
  formatTdProbability,
  isAnytimeTdUiEnabled,
} from '@/lib/anytimeTdDisplay';

describe('isAnytimeTdUiEnabled', () => {
  it('is false when unset or empty', () => {
    expect(isAnytimeTdUiEnabled(undefined)).toBe(false);
    expect(isAnytimeTdUiEnabled('')).toBe(false);
  });

  it('accepts 1, true, and yes (case-insensitive)', () => {
    expect(isAnytimeTdUiEnabled('1')).toBe(true);
    expect(isAnytimeTdUiEnabled('true')).toBe(true);
    expect(isAnytimeTdUiEnabled('TRUE')).toBe(true);
    expect(isAnytimeTdUiEnabled(' yes ')).toBe(true);
  });

  it('rejects other values', () => {
    expect(isAnytimeTdUiEnabled('0')).toBe(false);
    expect(isAnytimeTdUiEnabled('false')).toBe(false);
    expect(isAnytimeTdUiEnabled('on')).toBe(false);
  });
});

describe('formatTdProbability', () => {
  it('formats fractional probabilities as whole percent', () => {
    expect(formatTdProbability(0.237)).toBe('24%');
    expect(formatTdProbability(0.5)).toBe('50%');
  });

  it('formats whole-number percent inputs', () => {
    expect(formatTdProbability(42)).toBe('42%');
  });

  it('handles missing values', () => {
    expect(formatTdProbability(null)).toBe('—');
    expect(formatTdProbability(undefined)).toBe('—');
  });
});

describe('formatAnytimeTdEdge', () => {
  it('formats probability edges as signed percentage points', () => {
    expect(formatAnytimeTdEdge(0.05)).toBe('+5.0%');
    expect(formatAnytimeTdEdge(-0.032)).toBe('-3.2%');
    expect(formatAnytimeTdEdge(0)).toBe('0.0%');
  });

  it('handles missing values', () => {
    expect(formatAnytimeTdEdge(null)).toBe('—');
    expect(formatAnytimeTdEdge(undefined)).toBe('—');
    expect(formatAnytimeTdEdge('')).toBe('—');
  });
});

describe('formatMarketOdds', () => {
  it('formats American odds with sign', () => {
    expect(formatMarketOdds(150)).toBe('+150');
    expect(formatMarketOdds(-110)).toBe('-110');
  });

  it('handles missing values', () => {
    expect(formatMarketOdds(null)).toBe('—');
  });
});

describe('ANYTIME_TD_COLUMNS', () => {
  it('formats edge column as percentage points', () => {
    const edgeCol = ANYTIME_TD_COLUMNS.find((c) => c.key === 'edge');
    expect(edgeCol?.format?.(0.05, {})).toBe('+5.0%');
  });

  it('defines the expected board columns', () => {
    expect(ANYTIME_TD_COLUMNS.map((c) => c.label)).toEqual([
      'Player',
      'Pos',
      'Team',
      'Opp',
      'P(TD)',
      'Odds',
      'Edge',
      'Pick',
      'Conf',
    ]);
  });
});
