const { chromium } = require('@playwright/test');

async function testAuthenticatedPlayerCompare() {
  const browser = await chromium.launch({ headless: false, slowMo: 1000 });
  const context = await browser.newContext();
  const page = await context.newPage();

  // Enable console logging to catch JavaScript errors
  page.on('console', msg => {
    const type = msg.type();
    if (type === 'error' || type === 'warning' || type === 'log') {
      console.log(`[${type.toUpperCase()}]`, msg.text());
    }
  });
  
  page.on('pageerror', error => {
    console.log('JavaScript Error:', error.message);
  });

  // Set a fake auth token to simulate being logged in
  await page.addInitScript(() => {
    localStorage.setItem('auth_token', 'fake-token-for-testing');
  });

  try {
    console.log('Navigating to fantasy page with auth token...');
    await page.goto('http://localhost:3001/fantasy');
    
    // Wait for page to load
    await page.waitForTimeout(5000);
    
    console.log('Looking for Player Compare button...');
    
    // Look for the Player Compare button more broadly
    const compareButtons = await page.locator('text=/Compare/i').all();
    console.log(`Found ${compareButtons.length} buttons with "Compare" in text`);
    
    // Also look for the specific Player Compare button
    const playerCompareButton = page.locator('text="Player Compare"');
    const playerCompareCount = await playerCompareButton.count();
    console.log(`Found ${playerCompareCount} "Player Compare" buttons`);
    
    if (playerCompareCount > 0) {
      console.log('Clicking Player Compare button...');
      await playerCompareButton.click();
      await page.waitForTimeout(2000);
      
      // Look for player selection interface
      console.log('Looking for player selection UI...');
      
      // Check if there are any player checkboxes or selection elements
      const checkboxes = page.locator('input[type="checkbox"]');
      const checkboxCount = await checkboxes.count();
      console.log(`Found ${checkboxCount} checkboxes for player selection`);
      
      if (checkboxCount >= 2) {
        console.log('Selecting first 2 players...');
        await checkboxes.nth(0).check();
        await checkboxes.nth(1).check();
        
        // Look for Compare Players button
        const comparePlayersBtn = page.locator('text="Compare Players"');
        const comparePlayersBtnCount = await comparePlayersBtn.count();
        console.log(`Found ${comparePlayersBtnCount} "Compare Players" buttons`);
        
        if (comparePlayersBtnCount > 0) {
          console.log('Clicking Compare Players button...');
          
          // Listen for network requests to see what API calls are made
          page.on('request', request => {
            if (request.url().includes('/api/')) {
              console.log('API Request:', request.method(), request.url());
            }
          });
          
          page.on('response', response => {
            if (response.url().includes('/api/')) {
              console.log('API Response:', response.status(), response.url());
            }
          });
          
          await comparePlayersBtn.click();
          
          // Wait for potential API response
          await page.waitForTimeout(5000);
          
          console.log('Checking for comparison results or error messages...');
          
          // Look for error messages
          const errorMessages = page.locator('[class*="error"], [class*="Error"], text=/error/i, text=/failed/i');
          const errorCount = await errorMessages.count();
          
          if (errorCount > 0) {
            console.log('Found error messages:');
            for (let i = 0; i < errorCount; i++) {
              const errorText = await errorMessages.nth(i).textContent();
              console.log(`  Error ${i + 1}: ${errorText}`);
            }
          }
          
          // Look for comparison results
          const comparisonResults = page.locator('[class*="comparison"], [class*="compare"], [class*="result"]');
          const resultsCount = await comparisonResults.count();
          console.log(`Found ${resultsCount} elements that might be comparison results`);
          
        }
      }
    } else {
      // If Player Compare button not found, let's see what UI elements are available
      console.log('Player Compare button not found. Checking page content...');
      
      const buttons = page.locator('button');
      const buttonCount = await buttons.count();
      console.log(`Found ${buttonCount} total buttons:`);
      
      for (let i = 0; i < Math.min(buttonCount, 15); i++) {
        const buttonText = await buttons.nth(i).textContent();
        console.log(`  Button ${i + 1}: "${buttonText?.trim()}"`);
      }
      
      // Check if we're still on login page
      const loginElements = page.locator('text=/sign in|login/i');
      const loginCount = await loginElements.count();
      if (loginCount > 0) {
        console.log('Still seeing login elements - auth token might not be working');
      }
    }
    
  } catch (error) {
    console.error('Test error:', error);
  }

  await page.waitForTimeout(5000); // Keep browser open for manual inspection
  await browser.close();
}

testAuthenticatedPlayerCompare().catch(console.error);