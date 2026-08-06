import { COLUMN_HELP, PAGE_HELP, RECORD_HELP, RECORD_LABELS } from '../../src/lib/vault';

describe('vault help copy', () => {
  it('covers every record label with a help string', () => {
    for (const key of Object.keys(RECORD_LABELS)) {
      expect(RECORD_HELP[key]).toBeTruthy();
    }
  });

  it('keeps page and column help non-empty', () => {
    for (const text of Object.values(PAGE_HELP)) {
      expect(text.length).toBeGreaterThan(20);
    }
    for (const text of Object.values(COLUMN_HELP)) {
      expect(text.length).toBeGreaterThan(20);
    }
  });
});
