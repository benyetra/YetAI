import { test as base, expect } from '@playwright/test';

type FantasyFixtures = {
  fantasyPageReady: void;
};

export const test = base.extend<FantasyFixtures>({
  fantasyPageReady: [
    async ({ page }, use) => {
      await page.addInitScript(() => {
        localStorage.setItem('auth_token', 'playwright-test-token');
      });

      await page.route('**/api/auth/me', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'success',
            user: {
              id: 1,
              email: 'fantasy@test.com',
              username: 'testuser',
            },
          }),
        });
      });

      await page.route('**/api/fantasy/accounts', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'success',
            accounts: [
              {
                user_id: 'fu-1',
                platform: 'sleeper',
                username: 'testuser',
                platform_user_id: 'owner-1',
              },
            ],
          }),
        });
      });

      await page.route('**/api/fantasy/leagues', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'success',
            leagues: [
              {
                id: '1',
                league_id: 'league-abc',
                name: 'Test League',
                platform: 'sleeper',
                season: '2025',
                total_teams: 12,
                team_count: 12,
                scoring_type: 'ppr',
              },
            ],
          }),
        });
      });

      await page.route('**/api/fantasy/trending**', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'success',
            trending: [
              {
                player_id: 'p1',
                name: 'Trending Player',
                position: 'WR',
                team: 'KC',
                trend_count: 1200,
              },
            ],
          }),
        });
      });

      await page.route('**/api/fantasy/recommendations/start-sit/**', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'success',
            recommendations: [
              {
                league_id: 'league-abc',
                league_name: 'Test League',
                player_id: 'p1',
                player_name: 'Starter WR',
                position: 'WR',
                team: 'KC',
                recommendation: 'START',
                projected_points: 14.2,
                confidence: 0.82,
                reasoning: 'Strong recent usage',
                rank_in_position: 1,
                total_in_position: 3,
                week: 1,
                is_questionable: false,
              },
            ],
          }),
        });
      });

      await page.route('**/api/fantasy/recommendations/waiver-wire/**', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'success',
            recommendations: [
              {
                league_id: 'league-abc',
                league_name: 'Test League',
                player_id: 'p2',
                player_name: 'Waiver Target',
                position: 'RB',
                team: 'BUF',
                priority_score: 88,
                trend_count: 900,
                reason: 'Trending add',
              },
            ],
          }),
        });
      });

      await page.route('**/api/fantasy/matchups/**', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'success',
            matchups: [
              {
                matchup_id: '1',
                week: 1,
                team1: {
                  id: 1,
                  name: 'Team A',
                  owner_name: 'Owner A',
                  is_user_team: true,
                  score: 110.5,
                  starters: [],
                },
                team2: {
                  id: 2,
                  name: 'Team B',
                  owner_name: 'Owner B',
                  is_user_team: false,
                  score: 98.2,
                  starters: [],
                },
                status: 'completed',
                user_involved: true,
              },
            ],
          }),
        });
      });

      await page.route('**/api/v1/fantasy/standings/**', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'success',
            standings: [
              {
                rank: 1,
                team_id: 1,
                name: 'Team A',
                team_name: 'Team A',
                owner_name: 'Owner A',
                wins: 8,
                losses: 2,
                points_for: 1200,
              },
            ],
          }),
        });
      });

      await page.route('**/api/fantasy/leagues/**/rules', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'success',
            rules: {
              league_name: 'Test League',
              platform: 'sleeper',
              season: 2025,
              scoring_type: 'ppr',
              roster_positions: ['QB', 'RB', 'RB', 'WR', 'WR', 'TE', 'FLEX', 'BN'],
              scoring_settings: {
                receiving: { receptions: 1 },
              },
            },
          }),
        });
      });

      await use();
    },
    { auto: true },
  ],
});

export { expect };
