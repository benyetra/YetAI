/**
 * "Gamble It" — hand YetAI projections to Gambly (https://gambly.com), which turns a
 * natural-language bet description into a one-click betslip deep-linked to the user's
 * sportsbook. Uses Gambly's own Ask-Gambly entry point:
 *   https://gambly.com/chat?entry=ask-gambly&prompt=<text>&autoSubmit=1
 * Gambly has no public partner API, so this is a URL hand-off only (no keys, no backend).
 */
import { slipItemToSelection, slipKeyToBetType } from '@/lib/slip-to-bet';
import { fmtOdds } from '@/lib/yetai-format';
import { hasRealMatchup } from '@/lib/yetai-matchup';
import { asNumber, rowPersonName, type DiscoveryGroupConfig } from '@/lib/propDiscovery';
import type { DesignPick, SlipItem } from '@/components/yetai/types';

export const GAMBLY_CHAT_URL = 'https://gambly.com/chat';

/** Keep prompts well under URL limits and Gambly's handoff cap. */
export const GAMBLY_MAX_PROMPT_CHARS = 1500;

const FALSY_ENV = new Set(['0', 'false', 'no', 'off']);

/** On unless `NEXT_PUBLIC_GAMBLY_ENABLED` is explicitly 0/false/no/off. */
export function isGamblyEnabled(
  envValue: string | undefined = process.env.NEXT_PUBLIC_GAMBLY_ENABLED,
): boolean {
  if (envValue === undefined) return true;
  return !FALSY_ENV.has(envValue.trim().toLowerCase());
}

export function buildGamblyUrl(prompt: string): string {
  let text = prompt.trim().replace(/\s+\n/g, '\n');
  if (text.length > GAMBLY_MAX_PROMPT_CHARS) {
    text = `${text.slice(0, GAMBLY_MAX_PROMPT_CHARS - 1).trimEnd()}…`;
  }
  const params = new URLSearchParams({
    entry: 'ask-gambly',
    prompt: text,
    autoSubmit: '1',
    utm_source: 'yetai',
    utm_medium: 'referral',
    utm_campaign: 'gamble_it',
  });
  return `${GAMBLY_CHAT_URL}?${params.toString()}`;
}

/**
 * Turn one or more legs into a Gambly request. Two or more legs default to a parlay;
 * pass `parlay: false` for a slip of straight bets.
 */
export function gamblyPrompt(legs: string[], opts: { parlay?: boolean } = {}): string {
  const clean = legs.map((l) => l.trim()).filter(Boolean);
  if (clean.length === 0) return '';
  if (clean.length === 1) return `Build me a betslip: ${clean[0]}`;
  const parlay = opts.parlay ?? true;
  const header = parlay
    ? `Build me a ${clean.length}-leg parlay:`
    : `Build me a betslip with these ${clean.length} straight bets:`;
  return [header, ...clean.map((l, i) => `${i + 1}. ${l}`)].join('\n');
}

export function gamblyUrlForLegs(legs: string[], opts: { parlay?: boolean } = {}): string | null {
  const prompt = gamblyPrompt(legs, opts);
  return prompt ? buildGamblyUrl(prompt) : null;
}

function withOdds(text: string, odds: number | string | undefined | null): string {
  const n = typeof odds === 'string' ? Number(odds) : odds;
  if (n == null || !Number.isFinite(n) || n === 0) return text;
  return `${text} (${fmtOdds(n)})`;
}

const MARKET_LABEL: Record<ReturnType<typeof slipKeyToBetType>, string> = {
  moneyline: 'moneyline',
  spread: 'spread',
  total: 'total',
};

/** Bet-slip leg, e.g. "Buffalo Bills -3.5 spread (-110) — Buffalo Bills @ Atlanta Falcons". */
export function gamblyLegFromSlipItem(item: SlipItem): string {
  const selection = slipItemToSelection(item);
  const market = MARKET_LABEL[slipKeyToBetType(item.key)];
  const bet = withOdds(`${selection} ${market}`, item.odds);
  return item.matchup ? `${bet} — ${item.matchup}` : bet;
}

/** AI pick card leg. Player props without a real matchup fall back to the league. */
export function gamblyLegFromPick(pick: DesignPick): string {
  const betType = (pick.bet_type ?? '').trim();
  const addBetType =
    betType && betType.toLowerCase() !== 'prop' && !pick.pick.toLowerCase().includes(betType.toLowerCase());
  const bet = withOdds(addBetType ? `${pick.pick} ${betType}` : pick.pick, pick.odds);
  if (hasRealMatchup(pick.matchup)) return `${bet} — ${pick.matchup.trim()}`;
  return pick.league ? `${bet} (${pick.league})` : bet;
}

export type GamblyProjectionPick = {
  kind: 'ml' | 'spread' | 'total';
  /** Team name, or "Over"/"Under" for totals. */
  team: string;
  /** Market line text: "+1.5" for spreads, "8.5" for totals. */
  line?: string | null;
  odds?: number | null;
  matchup: string;
};

/** Game-projection model pick, e.g. "New York Yankees moneyline (-135) — Red Sox @ Yankees". */
export function gamblyLegFromProjection(p: GamblyProjectionPick): string {
  const line = p.line?.trim();
  let bet: string;
  if (p.kind === 'total') bet = `${p.team} ${line ?? ''} total`.replace(/\s+/g, ' ');
  else if (p.kind === 'spread') bet = line ? `${p.team} ${line} spread` : `${p.team} spread`;
  else bet = `${p.team} moneyline`;
  return `${withOdds(bet, p.odds)} — ${p.matchup}`;
}

/** Map a stat-group title to the prop market name Gambly understands. */
function propMarket(title: string): string {
  const t = title.trim();
  if (/^pra$/i.test(t)) return 'points + rebounds + assists';
  if (/best hit/i.test(t)) return 'hits';
  return t.toLowerCase();
}

function overUnder(raw: unknown): 'Over' | 'Under' | null {
  const s = String(raw ?? '').trim().toUpperCase();
  if (s.startsWith('OVER') || s === 'O') return 'Over';
  if (s.startsWith('UNDER') || s === 'U') return 'Under';
  return null;
}

/**
 * Best-edges player prop leg, e.g. "Jalen Brunson Over 26.5 points".
 * Hit-chance rows (no line) become "Aaron Judge to record a hit".
 */
export function gamblyLegFromDiscoveryRow(
  row: Record<string, unknown>,
  group: DiscoveryGroupConfig,
): string | null {
  const nameRaw = row[group.nameKey];
  const name = nameRaw != null && String(nameRaw).trim() ? String(nameRaw).trim() : rowPersonName(row);
  if (!name) return null;
  const market = propMarket(group.title);

  if (group.mode === 'projected_value') {
    return market === 'hits' ? `${name} to record a hit` : `${name} ${market}`;
  }

  const line = group.lineKey ? asNumber(row[group.lineKey]) : null;
  let side = overUnder(group.pickKey ? row[group.pickKey] : row.recommendation);
  if (!side && line != null && group.projectedKey) {
    const projected = asNumber(row[group.projectedKey]);
    if (projected != null && projected !== line) side = projected > line ? 'Over' : 'Under';
  }
  if (!side || line == null) return null;
  return `${name} ${side} ${line} ${market}`;
}
