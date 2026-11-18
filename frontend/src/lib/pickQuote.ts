/** The price a game pick is good at: the backend's explicit best quote (book, line, price). */
export type PickQuote = { line: number; price: number | null; book: string | null };

const BOOKS: Record<string, string> = {
  fanduel: 'FanDuel',
  draftkings: 'DraftKings',
  betmgm: 'BetMGM',
  williamhill_us: 'Caesars',
  espnbet: 'theScore Bet',
  betrivers: 'BetRivers',
  hardrockbet: 'Hard Rock Bet',
  pinnacle: 'Pinnacle',
  novig: 'Novig',
  prophetx: 'ProphetX',
};

export function bookName(key: unknown): string | null {
  const k = String(key ?? '').trim();
  return k ? (BOOKS[k.toLowerCase()] ?? k) : null;
}

/** "at -108, DraftKings" (price and book each optional). */
export function quoteNote(q: Pick<PickQuote, 'price' | 'book'>): string {
  const price = q.price == null ? '' : q.price > 0 ? `+${Math.round(q.price)}` : `${Math.round(q.price)}`;
  return [price && `at ${price}`, q.book].filter(Boolean).join(', ');
}

/** Read `<prefix>_best_line/price/book` off a merged game row; null when no pick quote was sent. */
export function pickQuoteOf(row: Record<string, unknown> | undefined, prefix: 'spread' | 'total'): PickQuote | null {
  const line = Number(row?.[`${prefix}_best_line`]);
  if (!row || row[`${prefix}_best_line`] == null || !Number.isFinite(line)) return null;
  const price = Number(row[`${prefix}_best_price`]);
  return {
    line,
    price: row[`${prefix}_best_price`] == null || !Number.isFinite(price) ? null : price,
    book: bookName(row[`${prefix}_best_book`]),
  };
}
