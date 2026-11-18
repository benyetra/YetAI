import { pickQuoteOf, quoteNote, quoteWhy } from '@/lib/pickQuote';
import { gamblyLegFromProjection } from '@/lib/gambly';

const row = {
  total_best_line: 221.5,
  total_best_price: -108,
  total_best_book: 'draftkings',
  total_pick_fair_prob: 0.5385,
  total_pick_ev: 0.031,
};

describe('pickQuote', () => {
  it('reads the explicit quote and says why in plain words', () => {
    const q = pickQuoteOf(row, 'total')!;
    expect(quoteNote(q)).toBe('at -108, DraftKings');
    expect(quoteWhy(q)).toBe('Best price -108 at DraftKings vs a fair price of -117 (+3.1% expected value)');
  });
  it('is null without a quote', () => {
    expect(pickQuoteOf({}, 'spread')).toBeNull();
    expect(pickQuoteOf(undefined, 'total')).toBeNull();
  });
  it('the Gamble It leg carries line, price and book', () => {
    expect(
      gamblyLegFromProjection({ kind: 'spread', team: 'Kansas City Chiefs', line: '+2.5', odds: -105, book: 'BetMGM', matchup: 'KC @ BUF' }),
    ).toBe('Kansas City Chiefs +2.5 spread (-105) at BetMGM — KC @ BUF');
  });
});
