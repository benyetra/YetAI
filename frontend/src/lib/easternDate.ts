/** Today's date in America/New_York (YYYY-MM-DD) — the day backend grading windows use. */
export function easternIso(now: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(now);
}
