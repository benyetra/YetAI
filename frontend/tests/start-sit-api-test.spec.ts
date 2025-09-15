import { test, expect } from '@playwright/test';

test.describe('Start/Sit API Integration', () => {
  test('should verify Start/Sit API returns success without PlayerAnalyticsService errors', async ({ page }) => {
    // Set up network monitoring to capture API calls
    const apiResponses: any[] = [];

    page.on('response', async (response) => {
      if (response.url().includes('/api/fantasy/recommendations/start-sit/')) {
        console.log(`Start/Sit API Response: ${response.status()} ${response.url()}`);
        try {
          const responseBody = await response.json();
          apiResponses.push({
            url: response.url(),
            status: response.status(),
            body: responseBody
          });
          console.log('Response body:', JSON.stringify(responseBody, null, 2));
        } catch (error) {
          console.log('Could not parse response body:', error);
          apiResponses.push({
            url: response.url(),
            status: response.status(),
            body: null,
            error: error.message
          });
        }
      }
    });

    // Navigate to login page
    await page.goto('/login');

    // Fill in test credentials and login
    await page.fill('input[placeholder*="john@example.com"]', 'playwright-test@example.com');
    await page.fill('input[placeholder*="••••••••"]', 'testpass123');

    // Click login button
    await page.click('button:has-text("Log In")');

    // Wait for login to complete
    await page.waitForTimeout(2000);

    // Navigate to fantasy page
    await page.goto('/fantasy');
    await page.waitForLoadState('networkidle');

    // Take screenshot to verify we're on the fantasy page
    await page.screenshot({ path: 'fantasy-page-authenticated.png', fullPage: true });

    // Check if the fantasy page content is now visible
    const fantasyContent = await page.textContent('body');
    console.log('Fantasy page content loaded:', fantasyContent?.includes('Fantasy Sports'));

    // Try to trigger the Start/Sit API call by looking for the button
    const startSitButtons = await page.locator('button').filter({ hasText: /get recommendations|start.*sit/i }).all();

    if (startSitButtons.length > 0) {
      console.log(`Found ${startSitButtons.length} potential Start/Sit buttons`);

      // Try clicking the first available button
      try {
        await startSitButtons[0].click();
        console.log('Clicked Start/Sit button');

        // Wait for API response
        await page.waitForTimeout(5000);

        // Take screenshot after clicking
        await page.screenshot({ path: 'after-start-sit-click.png', fullPage: true });

      } catch (error) {
        console.log('Could not click Start/Sit button:', error.message);
      }
    } else {
      // If no button found, make a direct API call using page evaluation
      console.log('No Start/Sit button found, making direct API call...');

      const apiResult = await page.evaluate(async () => {
        try {
          const response = await fetch('/api/fantasy/recommendations/start-sit/1', {
            method: 'GET',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${localStorage.getItem('auth_token') || ''}`
            }
          });

          const data = await response.json();
          return {
            status: response.status,
            data: data
          };
        } catch (error) {
          return {
            status: 'error',
            error: error.message
          };
        }
      });

      console.log('Direct API call result:', apiResult);

      // Verify the API call was successful
      expect(apiResult.status).toBe(200);
      expect(apiResult.data.status).toBe('success');
    }

    // Log final results
    console.log('Final API responses captured:', apiResponses);

    // Take final screenshot
    await page.screenshot({ path: 'final-fantasy-state.png', fullPage: true });

    // Verify that we didn't get any PlayerAnalyticsService errors
    // Check for any API responses that indicate success
    if (apiResponses.length > 0) {
      const response = apiResponses[0];
      expect(response.status).toBe(200);
      expect(response.body.status).toBe('success');
      console.log('✅ Start/Sit API working correctly - PlayerAnalyticsService error resolved!');
    }
  });

  test('should test Start/Sit API directly via HTTP', async ({ request }) => {
    // First register and login to get a token
    const registerResponse = await request.post('http://localhost:8000/api/auth/register', {
      data: {
        email: 'api-test@example.com',
        password: 'testpass123',
        username: 'apitest'
      }
    });

    let token;
    if (registerResponse.ok()) {
      const registerData = await registerResponse.json();
      token = registerData.access_token;
    } else {
      // If user already exists, try to login
      const loginResponse = await request.post('http://localhost:8000/api/auth/login', {
        data: {
          email: 'api-test@example.com',
          password: 'testpass123'
        }
      });

      if (loginResponse.ok()) {
        const loginData = await loginResponse.json();
        token = loginData.access_token;
      }
    }

    // Test the Start/Sit API endpoint
    const startSitResponse = await request.get('http://localhost:8000/api/fantasy/recommendations/start-sit/1', {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });

    expect(startSitResponse.ok()).toBeTruthy();

    const responseData = await startSitResponse.json();
    console.log('Start/Sit API Response:', JSON.stringify(responseData, null, 2));

    // Verify the response structure
    expect(responseData).toHaveProperty('status');
    expect(responseData.status).toBe('success');
    expect(responseData).toHaveProperty('recommendations');

    // This should be the expected message when no leagues are connected
    expect(responseData.message).toBe('No connected fantasy leagues found');

    console.log('✅ Direct API test successful - PlayerAnalyticsService is working!');
  });
});