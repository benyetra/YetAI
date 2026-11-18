import { test, expect, type Page } from '@playwright/test';
import { mkdirSync } from 'fs';
import { boardPayload, type BoardSport, type BoardState } from './fixtures/board-fixtures';

const SPORTS: BoardSport[] = ['nba', 'nfl', 'nhl'];
const STATES: BoardState[] = ['withheld', 'open', 'openGames', 'empty'];
const NOTE = 'No pick: this market has not proved itself against the line yet';
const EMPTY_BEST_EDGES = 'No picks today: no market on this board has proved itself against the line yet';
/** Only the NBA board has a Best edges strip (and so Gamble It). */
const HAS_BEST_EDGES: Record<BoardSport, boolean> = { nba: true, nfl: false, nhl: false };
/** openGames: the pick each board shows (the card's market, line, price and book), what its Gamble It
 *  leg must say, and how many open games fail the EV gates. */
const OPEN_GAMES: Record<BoardSport, { picks: Array<{ text: RegExp; gamble: RegExp }>; noPlay: number }> = {
  nba: {
    picks: [
      { text: /Miami Heat\s*Spread -3\.5\s*at -110, FanDuel/, gamble: /Miami Heat -3\.5 spread \(-110\) at FanDuel/ },
      // spread fails, total passes: the card shows the total
      { text: /Over\s*221\.5\s*at -108, DraftKings/, gamble: /Over 221\.5 total \(-108\) at DraftKings/ },
    ],
    noPlay: 1,
  },
  nfl: {
    // the pick follows best_side (the away team, against the model's home lean); the total's EV is lower
    picks: [{ text: /Kansas City Chiefs\s*Spread \+2\.5\s*at -105, BetMGM/, gamble: /Kansas City Chiefs \+2\.5 spread \(-105\) at BetMGM/ }],
    noPlay: 1,
  },
  nhl: {
    picks: [{ text: /Over\s*5\.5\s*at -108, DraftKings/, gamble: /Over 5\.5 total \(-108\) at DraftKings/ }],
    noPlay: 1,
  },
};
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
  // Team logos are lazy <img>s: wait for them so screenshots (and layout) are the settled page.
  await page.waitForFunction(() => Array.from(document.images).every((i) => i.complete));
  return errors;
}

for (const sport of SPORTS) {
  test.describe(`${sport.toUpperCase()} board`, () => {
    test('every market withheld: note, no pick UI', async ({ page }) => {
      const errors = await load(page, sport, 'withheld');
      await expect(page.getByText(NOTE).first()).toBeVisible();
      if (HAS_BEST_EDGES[sport]) await expect(page.getByText(EMPTY_BEST_EDGES)).toBeVisible();
      await expect(page.locator(GAMBLE)).toHaveCount(0);
      // No table cell and no Best edges row may carry a pick side.
      await expect(page.locator('td', { hasText: /^\s*(OVER|UNDER|HOME|AWAY)\b/i })).toHaveCount(0);
      await expect(page.locator('.predictions-discovery-pick')).toHaveCount(0);
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

    test('open game market: pick with book and price on the game card, Gamble It', async ({ page }) => {
      const errors = await load(page, sport, 'openGames');
      const { picks, noPlay } = OPEN_GAMES[sport];
      const cards = page.locator('.proj-card');
      await expect(cards).toHaveCount(picks.length + noPlay);
      const picked = cards.filter({ has: page.locator('.proj-pick:not(.is-none)') });
      const failing = cards.filter({ has: page.locator('.proj-pick.is-none') });
      await expect(picked).toHaveCount(picks.length);
      await expect(failing).toHaveCount(noPlay);
      for (const { text, gamble } of picks) {
        // The pick states market, line, price and book; the card says why in plain words, not a model edge.
        const card = picked.filter({ has: page.locator('.proj-pick-bet', { hasText: text }) });
        await expect(card).toHaveCount(1);
        await expect(card.locator('.proj-verdict')).toHaveText('Pick');
        await expect(card.locator('.proj-pick-why')).toContainText(/Best price -?\d+ at .+ vs a fair price of -?\d+ \(\+[\d.]+% expected value\)/);
        await expect(card.locator('.proj-pick-why')).not.toContainText(/edge|projects/i);
        await expect(card.locator('.proj-pick-bet')).not.toContainText('Spread / ML');
        await expect(card.locator('.proj-card-flag, .proj-verdict.v-strong')).toHaveCount(0);
        // Gamble It carries the same side, line, price and book.
        const href = await card.locator(GAMBLE).getAttribute('href');
        expect(new URL(href ?? '').searchParams.get('prompt')).toMatch(gamble);
        await expect(card.getByText(NOTE)).toHaveCount(0);
      }
      // An open market whose row failed the EV gates: neutral, no team named, not the "not proved" note.
      for (let i = 0; i < noPlay; i++) {
        const card = failing.nth(i);
        await expect(card.locator('.proj-pick')).toContainText('No play at current prices');
        await expect(card.locator('.proj-pick')).not.toContainText('Model leans');
        await expect(card.locator('.proj-verdict')).toHaveText('No pick');
        await expect(card.getByText(NOTE)).toHaveCount(0);
        await expect(card.locator(GAMBLE)).toHaveCount(0);
      }
      // Props are still withheld.
      await expect(page.getByText(NOTE).first()).toBeVisible();
      await expect(page.locator('.prop-pick-cell', { hasText: /^OVER/ })).toHaveCount(0);
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
