const { chromium } = require('@playwright/test');

async function testPlayerCompare() {
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext();
  const page = await context.newPage();

  // Enable console logging
  page.on('console', msg => console.log('PAGE LOG:', msg.text()));
  page.on('pageerror', error => console.log('PAGE ERROR:', error));

  try {
    console.log('Navigating to fantasy page...');
    await page.goto('http://localhost:3001/fantasy');
    
    // Wait for page to load
    await page.waitForTimeout(3000);
    
    console.log('Looking for Player Compare button...');
    
    // Look for the Player Compare button
    const compareButton = page.locator('text=Player Compare');
    if (await compareButton.count() > 0) {
      console.log('Found Player Compare button, clicking...');
      await compareButton.click();
      
      // Wait a bit and check for any errors
      await page.waitForTimeout(2000);
      
      console.log('Checking for error messages...');
      const errorElements = page.locator('[class*="error"], [class*="Error"], text=/error/i');
      const errorCount = await errorElements.count();
      
      if (errorCount > 0) {
        for (let i = 0; i < errorCount; i++) {
          const errorText = await errorElements.nth(i).textContent();
          console.log(`Error ${i + 1}: ${errorText}`);
        }
      } else {
        console.log('No error messages found');
      }
      
      // Check if we need to login
      const loginElements = page.locator('text=/sign in|login|authenticate/i');
      const loginCount = await loginElements.count();
      if (loginCount > 0) {
        console.log('Authentication required - found login prompts');
      }
      
      // Check local storage for auth token
      const authToken = await page.evaluate(() => localStorage.getItem('auth_token'));
      console.log('Auth token in localStorage:', authToken ? 'Present' : 'Missing');
      
    } else {
      console.log('Player Compare button not found');
      
      // List all buttons on the page
      const buttons = page.locator('button');
      const buttonCount = await buttons.count();
      console.log(`Found ${buttonCount} buttons on page:`);
      
      for (let i = 0; i < Math.min(buttonCount, 10); i++) {
        const buttonText = await buttons.nth(i).textContent();
        console.log(`  Button ${i + 1}: "${buttonText?.trim()}"`);
      }
    }
    
  } catch (error) {
    console.error('Test error:', error);
  }

  await browser.close();
}

testPlayerCompare().catch(console.error);