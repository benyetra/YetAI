/** Shared matchup helpers for YetAI pick cards. */

export function isPlaceholderMatchup(matchup: string): boolean {
  const m = (matchup || '').trim().toLowerCase();
  if (!m) return true;
  if (m === 'matchup pending' || m === 'tbd') return true;
  if (m.endsWith(' player prop')) return true;
  return false;
}

export function hasRealMatchup(matchup: string): boolean {
  const m = (matchup || '').trim();
  if (isPlaceholderMatchup(m)) return false;
  if (m.includes('@')) return true;
  if (/\s+vs\.?\s+/i.test(m)) return true;
  if (/^vs\s+/i.test(m)) return true;
  return false;
}

export function isPlayerPropDisplay(
  betType: string | undefined,
  matchup: string,
): boolean {
  if ((betType || '').toLowerCase() === 'prop') return true;
  return !hasRealMatchup(matchup);
}
