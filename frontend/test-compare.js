const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();
  
  try {
    // Go to the login page
    await page.goto('http://localhost:3001/login');
    await page.waitForTimeout(2000);
    
    // Login (using email/password fields)
    await page.fill('input[placeholder*="@example.com"]', 'testuser@example.com');
    await page.fill('input[type="password"]', 'testpass123');
    await page.click('button:has-text("Log In")');
    
    // Wait for login and then navigate to fantasy page
    await page.waitForTimeout(3000);
    
    // Check if we're logged in by looking for dashboard elements, then navigate to fantasy
    try {
      await page.waitForSelector('body', { timeout: 5000 });
      console.log('Navigating to fantasy page...');
      await page.goto('http://localhost:3001/fantasy');
      await page.waitForTimeout(3000);
    } catch (error) {
      console.log('Login may have failed, taking screenshot for debugging');
      await page.screenshot({ path: 'login-debug.png', fullPage: true });
    }
    
    // Take initial screenshot to see current state
    await page.screenshot({ path: 'fantasy-page-initial.png', fullPage: true });
    console.log('Initial fantasy page screenshot saved');
    
    // Click the player compare button
    console.log('Looking for player compare button...');
    try {
      const compareButton = await page.locator('button:has-text("Player Compare")').first();
      await compareButton.click({ timeout: 5000 });
    } catch (error) {
      console.log('Could not find Player Compare button, trying alternative selectors...');
      // Try other possible selectors
      const altButton = await page.locator('button').filter({ hasText: 'Compare' }).first();
      await altButton.click({ timeout: 5000 });
    }
    
    await page.waitForTimeout(2000);
    
    // Take screenshot of the player search interface
    await page.screenshot({ path: 'player-search-interface.png', fullPage: true });
    console.log('Screenshot of player search interface saved');
    
    // If search interface is visible, try to select two players
    const searchInput = await page.locator('input[placeholder*="Search"]').first();
    if (await searchInput.isVisible()) {
      // Search for first player
      await searchInput.fill('Josh Allen');
      await page.waitForTimeout(1000);
      
      // Click on first result
      const firstResult = await page.locator('.player-result').first();
      if (await firstResult.isVisible()) {
        await firstResult.click();
        await page.waitForTimeout(1000);
        
        // Search for second player
        await searchInput.fill('Lamar Jackson');
        await page.waitForTimeout(1000);
        
        // Click on second result
        const secondResult = await page.locator('.player-result').first();
        if (await secondResult.isVisible()) {
          await secondResult.click();
          await page.waitForTimeout(2000);
          
          // Take screenshot of comparison
          await page.screenshot({ path: 'player-comparison-with-data.png', fullPage: true });
          console.log('Screenshot of player comparison saved');
        }
      }
    }
    
  } catch (error) {
    console.error('Error:', error);
    await page.screenshot({ path: 'error-screenshot.png', fullPage: true });
  } finally {
    await browser.close();
  }
})();