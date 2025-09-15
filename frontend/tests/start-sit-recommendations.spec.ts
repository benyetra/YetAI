import { test, expect } from '@playwright/test';

test.describe('Start/Sit Recommendations', () => {
  test.beforeEach(async ({ page }) => {
    // Set up network monitoring to capture API calls
    await page.route('**/api/**', route => {
      console.log(`API call: ${route.request().method()} ${route.request().url()}`);
      route.continue();
    });
  });

  test('should load fantasy page and display Start/Sit button', async ({ page }) => {
    // Navigate to the fantasy page
    await page.goto('/fantasy');

    // Wait for the page to load
    await page.waitForLoadState('networkidle');

    // Take a screenshot for debugging
    await page.screenshot({ path: 'fantasy-page-initial.png', fullPage: true });

    // Check if the page loaded correctly
    await expect(page).toHaveTitle(/Fantasy/i);

    // Look for the Start/Sit recommendations section
    const startSitSection = page.locator('text=AI Start/Sit Recommendations');
    await expect(startSitSection).toBeVisible();

    // Look for the "Get Recommendations" button
    const getRecommendationsButton = page.locator('button:has-text("Get Recommendations")');
    await expect(getRecommendationsButton).toBeVisible();

    console.log('✓ Fantasy page loaded successfully with Start/Sit section');
  });

  test('should click Start/Sit Recommendations button and check API response', async ({ page }) => {
    // Set up API response monitoring
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

    // Navigate to fantasy page
    await page.goto('/fantasy');
    await page.waitForLoadState('networkidle');

    // Look for and click the "Get Recommendations" button
    const getRecommendationsButton = page.locator('button:has-text("Get Recommendations")');
    await expect(getRecommendationsButton).toBeVisible();

    // Take a screenshot before clicking
    await page.screenshot({ path: 'before-clicking-recommendations.png', fullPage: true });

    // Click the button
    await getRecommendationsButton.click();

    // Wait for the API call to complete
    await page.waitForTimeout(3000);

    // Take a screenshot after clicking
    await page.screenshot({ path: 'after-clicking-recommendations.png', fullPage: true });

    // Check if loading state appears
    const loadingIndicator = page.locator('text=Loading...');
    console.log('Loading indicator visible:', await loadingIndicator.isVisible());

    // Wait for either success or error state
    await page.waitForTimeout(5000);

    // Check for error messages
    const errorMessages = await page.locator('[class*="error"], [class*="Error"], text=error, text=Error').allTextContents();
    if (errorMessages.length > 0) {
      console.log('Error messages found:', errorMessages);
    }

    // Check for success indicators
    const successElements = await page.locator('[class*="success"], text=Recommendations').allTextContents();
    if (successElements.length > 0) {
      console.log('Success elements found:', successElements);
    }

    // Log the API responses we captured
    console.log('Captured API responses:', apiResponses);

    // Take final screenshot
    await page.screenshot({ path: 'final-recommendations-state.png', fullPage: true });

    // Verify we got an API response
    expect(apiResponses.length).toBeGreaterThan(0);

    if (apiResponses.length > 0) {
      const response = apiResponses[0];
      console.log('API Response Status:', response.status);
      console.log('API Response Body:', response.body);

      // Check if we got a 200 response
      if (response.status === 200) {
        expect(response.body).toBeDefined();
        expect(response.body.status).toBe('success');
        console.log('✓ API returned successful response');
      } else {
        console.log('⚠ API returned non-200 status:', response.status);
        console.log('Response body:', response.body);
      }
    }
  });

  test('should verify no PlayerAnalyticsService errors in console', async ({ page }) => {
    const consoleMessages: string[] = [];
    const errorMessages: string[] = [];

    // Listen for console messages
    page.on('console', msg => {
      const text = msg.text();
      consoleMessages.push(text);
      if (msg.type() === 'error') {
        errorMessages.push(text);
        console.log('Console error:', text);
      }
    });

    // Navigate to fantasy page
    await page.goto('/fantasy');
    await page.waitForLoadState('networkidle');

    // Click the Start/Sit recommendations button
    const getRecommendationsButton = page.locator('button:has-text("Get Recommendations")');
    await getRecommendationsButton.click();

    // Wait for operations to complete
    await page.waitForTimeout(5000);

    // Check for PlayerAnalyticsService errors
    const analyticsErrors = errorMessages.filter(msg =>
      msg.includes('PlayerAnalyticsService') ||
      msg.includes('analytics') ||
      msg.includes('database') ||
      msg.includes('SQL')
    );

    console.log('All console messages:', consoleMessages);
    console.log('Error messages:', errorMessages);
    console.log('Analytics-related errors:', analyticsErrors);

    // Verify no PlayerAnalyticsService errors
    expect(analyticsErrors).toHaveLength(0);
    console.log('✓ No PlayerAnalyticsService errors found');
  });

  test('should handle API errors gracefully', async ({ page }) => {
    // Navigate to fantasy page
    await page.goto('/fantasy');
    await page.waitForLoadState('networkidle');

    // Mock the API to return an error
    await page.route('**/api/fantasy/recommendations/start-sit/**', route => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'error',
          message: 'PlayerAnalyticsService error: Database connection failed'
        })
      });
    });

    // Click the Start/Sit recommendations button
    const getRecommendationsButton = page.locator('button:has-text("Get Recommendations")');
    await getRecommendationsButton.click();

    // Wait for the error to be handled
    await page.waitForTimeout(3000);

    // Take screenshot of error state
    await page.screenshot({ path: 'error-handling-state.png', fullPage: true });

    // Check that the error is displayed to the user
    const errorMessage = page.locator('text=Failed to load start/sit recommendations');
    await expect(errorMessage).toBeVisible();

    console.log('✓ Error handling works correctly');
  });
});