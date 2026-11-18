/** The price a game pick is good at: the backend's explicit best quote (book, line, price). */
export type PickQuote = {
  line: number;
  price: number | null;
  book: string | null;
  /** The backend's consensus fair probability and expected value for the picked side. */
  fairProb: number | null;
  ev: number | null;
};

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
  const opt = (k: string): number | null => {
    const v = row[`${prefix}_${k}`];
    return v == null || !Number.isFinite(Number(v)) ? null : Number(v);
  };
  return {
    line,
    price: opt('best_price'),
    book: bookName(row[`${prefix}_best_book`]),
    fairProb: opt('pick_fair_prob'),
    ev: opt('pick_ev'),
  };
}

function american(n: number): string {
  return n > 0 ? `+${Math.round(n)}` : `${Math.round(n)}`;
}

/** The fair price a probability stands for, as American odds. */
function fairPrice(p: number): string {
  return american(p >= 0.5 ? (-100 * p) / (1 - p) : (100 * (1 - p)) / p);
}

/** Why a priced pick is a pick, in plain words ("Best price -105 at BetMGM vs a fair price of -112 (+2.4% expected value)"). */
export function quoteWhy(q: PickQuote): string {
  const best = ['Best price', q.price != null ? american(q.price) : '', q.book ? `at ${q.book}` : '']
    .filter(Boolean)
    .join(' ');
  const fair = q.fairProb != null && q.fairProb > 0 && q.fairProb < 1 ? ` vs a fair price of ${fairPrice(q.fairProb)}` : '';
  const ev = q.ev != null ? ` (${q.ev >= 0 ? '+' : ''}${(q.ev * 100).toFixed(1)}% expected value)` : '';
  return `${best}${fair}${ev}`;
}
