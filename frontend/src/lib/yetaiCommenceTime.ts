/** ISO UTC start to send when placing a bet from a YetAI pick. `game_time` is a display
 * string ("11/13/2026 @7:30 PM ET") that JS cannot parse; the API's `commence_time` is ISO
 * with a Z. Returns undefined when unknown so the backend uses the pick's stored start. */
export function placementCommenceTime(bet: { commence_time?: string | null }): string | undefined {
  const d = bet.commence_time ? new Date(bet.commence_time) : null;
  return d && !isNaN(d.getTime()) ? d.toISOString() : undefined;
}
