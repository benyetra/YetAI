import { SPORT_OPTIONS, BET_TYPE_OPTIONS } from './options';

test('ungradeable sports and partial-game markets are not offered', () => {
  expect(SPORT_OPTIONS).not.toContain('Tennis');
  expect(BET_TYPE_OPTIONS).not.toContain('1st Half');
  expect(BET_TYPE_OPTIONS).not.toContain('1st Quarter');
  expect(BET_TYPE_OPTIONS).toContain('Run Line');
});
