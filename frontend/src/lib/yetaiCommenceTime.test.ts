import { placementCommenceTime } from './yetaiCommenceTime';

test('uses the ISO UTC start, never the display game_time', () => {
  const bet = { commence_time: '2026-11-14T00:30:00Z', game_time: '11/13/2026 @7:30 PM ET' };
  expect(placementCommenceTime(bet)).toBe('2026-11-14T00:30:00.000Z');
});

test('unknown or invalid start gives undefined (backend falls back to the pick)', () => {
  expect(placementCommenceTime({})).toBeUndefined();
  expect(placementCommenceTime({ commence_time: null })).toBeUndefined();
  expect(placementCommenceTime({ commence_time: 'nope' })).toBeUndefined();
});
