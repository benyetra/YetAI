import { easternIso } from './easternDate';

describe('easternIso', () => {
  it('uses the New York date, not the browser/UTC date', () => {
    // 03:30 UTC on Nov 13 is still Nov 12 evening in New York.
    expect(easternIso(new Date('2026-11-13T03:30:00Z'))).toBe('2026-11-12');
    // 05:30 UTC on Nov 13 is past midnight in New York (EST).
    expect(easternIso(new Date('2026-11-13T05:30:00Z'))).toBe('2026-11-13');
  });
});
