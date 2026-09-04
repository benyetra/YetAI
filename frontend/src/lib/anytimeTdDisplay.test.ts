import {
  ANYTIME_TD_COLUMNS,
  formatAnytimeTdEdge,
  formatMarketOdds,
  formatTdProbability,
  isAnytimeTdUiEnabled,
} from '@/lib/anytimeTdDisplay';

describe('isAnytimeTdUiEnabled', () => {
  it('is true when unset or empty (walk-forward gate passed)', () => {
    expect(isAnytimeTdUiEnabled(undefined)).toBe(true);
    expect(isAnytimeTdUiEnabled('')).toBe(true);
  });

  it('accepts 1, true, yes, and on (case-insensitive)', () => {
    expect(isAnytimeTdUiEnabled('1')).toBe(true);
    expect(isAnytimeTdUiEnabled('true')).toBe(true);
    expect(isAnytimeTdUiEnabled('TRUE')).toBe(true);
    expect(isAnytimeTdUiEnabled(' yes ')).toBe(true);
    expect(isAnytimeTdUiEnabled('on')).toBe(true);
  });

  it('rejects explicit off values', () => {
    expect(isAnytimeTdUiEnabled('0')).toBe(false);
    expect(isAnytimeTdUiEnabled('false')).toBe(false);
    expect(isAnytimeTdUiEnabled('no')).toBe(false);
    expect(isAnytimeTdUiEnabled('off')).toBe(false);
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
