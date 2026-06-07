import { test, expect } from './fixtures/fantasy-auth.fixture';

test.describe('Fantasy page with auth stubs', () => {
  test('loads connected league tools and trending players', async ({ page }) => {
    await page.goto('/fantasy');
    await page.waitForLoadState('networkidle');

    await expect(page.getByText('Test League')).toBeVisible();
    await expect(page.getByText('Trending Players')).toBeVisible();
    await expect(page.getByText('Trending Player')).toBeVisible();
  });

  test('start/sit recommendations happy path', async ({ page }) => {
    await page.goto('/fantasy');
    const startSitCard = page.locator('.card', {
      has: page.getByRole('heading', { name: 'AI Start/Sit Recommendations' }),
    });
    await startSitCard.getByRole('button', { name: /Get Recommendations/i }).click();
    await expect(page.getByText('Starter WR')).toBeVisible({ timeout: 10000 });
  });

  test('waiver recommendations happy path', async ({ page }) => {
    await page.goto('/fantasy');
    const waiverCard = page.locator('.card', {
      has: page.getByRole('heading', { name: 'Waiver Wire Targets' }),
    });
    await waiverCard.getByRole('button', { name: /Get Recommendations/i }).click();
    await expect(page.getByText('Waiver Target')).toBeVisible({ timeout: 10000 });
  });

  test('matchups view from league card', async ({ page }) => {
    await page.goto('/fantasy');
    await page.getByRole('button', { name: 'Matchups' }).click();
    await expect(page.getByText('Week 1 Matchups')).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('Team A')).toBeVisible();
    await expect(page.getByText('110.5 - 98.2')).toBeVisible();
  });

  test('trade analyzer opens with league context', async ({ page }) => {
    await page.goto('/fantasy');
    await page.getByRole('button', { name: 'Trade Analyzer' }).click();
    await expect(page.getByRole('heading', { name: 'Trade Analyzer' })).toBeVisible({
      timeout: 10000,
    });
  });
});
