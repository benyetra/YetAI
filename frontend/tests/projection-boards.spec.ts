import { test, expect, type Page } from '@playwright/test';
import { mkdirSync } from 'fs';
import { boardPayload, type BoardSport, type BoardState } from './fixtures/board-fixtures';

const SPORTS: BoardSport[] = ['nba', 'nfl', 'nhl'];
const STATES: BoardState[] = ['withheld', 'open', 'empty'];
const NOTE = 'No pick: this market has not proved itself against the line yet';
const EMPTY_BEST_EDGES = 'No picks today: no market on this board has proved itself against the line yet';
/** Only the NBA board has a Best edges strip (and so Gamble It). */
const HAS_BEST_EDGES: Record<BoardSport, boolean> = { nba: true, nfl: false, nhl: false };
const GAMBLE = 'a[title="Build a one-click betslip on Gambly"]';
const SCREENS = process.env.BOARD_SCREENS_DIR || 'test-results/board-screens';

function authToken(): string {
  const enc = (v: object) => Buffer.from(JSON.stringify(v)).toString('base64url');
  return `${enc({ alg: 'HS256', typ: 'JWT' })}.${enc({ sub: '1', exp: Math.floor(Date.now() / 1000) + 86400 })}.sig`;
}

async function mockBoard(page: Page, sport: BoardSport, state: BoardState) {
  // The app opens ws://localhost:8000/ws/<user>; with no backend it logs a refused-connection error (the dev overlay's "1 Issue"). Accept it silently.
  await page.routeWebSocket(/\/ws\//, () => {});
  const user = { id: 1, email: 'boards@test.com', username: 'testuser', is_verified: true, is_premium: true };
  await page.addInitScript(
    ({ token, u }) => {
      localStorage.setItem('auth_token', token);
      localStorage.setItem('user_data', JSON.stringify(u));
    },
    { token: authToken(), u: user },
  );
  // Catch-all first (Playwright runs the most recently registered matching route first).
  await page.route('**/api/**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'success' }) }),
  );
  await page.route('**/api/auth/me', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'success', user }) }),
  );
  await page.route(`**/api/v1/predictions/${sport}**`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(boardPayload(sport, state)) }),
  );
}

async function load(page: Page, sport: BoardSport, state: BoardState) {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => m.type() === 'error' && errors.push(`console: ${m.text()}`));
  await mockBoard(page, sport, state);
  await page.goto(`/predictions/${sport}`);
  await expect(page.getByRole('heading', { name: `${sport.toUpperCase()} Stat Projections`, exact: false })).toBeVisible();
  await expect(page.getByText('Loading…')).toHaveCount(0);
  return errors;
}

for (const sport of SPORTS) {
  test.describe(`${sport.toUpperCase()} board`, () => {
    test('every market withheld: note, no pick UI', async ({ page }) => {
      const errors = await load(page, sport, 'withheld');
      await expect(page.getByText(NOTE).first()).toBeVisible();
      if (HAS_BEST_EDGES[sport]) await expect(page.getByText(EMPTY_BEST_EDGES)).toBeVisible();
      await expect(page.locator(GAMBLE)).toHaveCount(0);
      expect(errors).toEqual([]);
    });

    test('one market open: pick shown with Gamble It', async ({ page }) => {
      const errors = await load(page, sport, 'open');
      await expect(page.getByText(NOTE).first()).toBeVisible(); // the rest stay withheld
      await expect(page.getByText(EMPTY_BEST_EDGES)).toHaveCount(0);
      await expect(page.locator('.prop-pick-cell', { hasText: /^OVER/ }).first()).toBeVisible();
      if (HAS_BEST_EDGES[sport]) {
        await expect(page.locator('.predictions-discovery-pick').first()).toHaveText(/OVER/);
        await expect(page.locator(GAMBLE).first()).toBeVisible();
      } else {
        await expect(page.locator(GAMBLE)).toHaveCount(0); // these boards have no Gamble It on props
      }
      expect(errors).toEqual([]);
    });

    test('no data: empty state, no errors', async ({ page }) => {
      const errors = await load(page, sport, 'empty');
      await expect(page.getByText('No predictions available for this date.').first()).toBeVisible();
      await expect(page.getByText(NOTE)).toHaveCount(0);
      await expect(page.locator(GAMBLE)).toHaveCount(0);
      expect(errors).toEqual([]);
    });
  });
}

// Screenshots: BOARD_SCREENS=1 [BOARD_SCREENS_DIR=<dir>, default test-results/board-screens] [BOARD_SHOTS_SUBDIR=before|after] npx playwright test tests/projection-boards.spec.ts -g screenshots
test.describe('board screenshots', () => {
  test.skip(!process.env.BOARD_SCREENS, 'set BOARD_SCREENS=1 to capture');
  const dir = `${SCREENS}/${process.env.BOARD_SHOTS_SUBDIR || 'after'}`;
  for (const sport of SPORTS)
    for (const state of STATES)
      for (const [name, width, height] of [['desktop', 1440, 900], ['phone', 390, 844]] as const)
        test(`${sport}-${state}-${name}`, async ({ page }) => {
          mkdirSync(dir, { recursive: true });
          await page.setViewportSize({ width, height });
          await load(page, sport, state);
          await page.screenshot({ path: `${dir}/${sport}-${state}-${name}.png`, fullPage: true });
          const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
          console.log(`${sport}-${state}-${name} horizontal overflow px: ${overflow}`);
        });
});
