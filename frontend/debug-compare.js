const { chromium } = require('@playwright/test');

async function debugPlayerCompare() {
  const browser = await chromium.launch({ 
    headless: false, 
    devtools: true  // Open devtools to see console
  });
  const context = await browser.newContext();
  const page = await context.newPage();

  // Log all console messages
  page.on('console', msg => {
    console.log(`[${msg.type().toUpperCase()}] ${msg.text()}`);
  });
  
  page.on('pageerror', error => {
    console.log('JavaScript Error:', error.message);
    console.log('Stack:', error.stack);
  });

  // Listen for network requests to see API calls
  page.on('request', request => {
    if (request.url().includes('/api/')) {
      console.log('🔵 API Request:', request.method(), request.url());
    }
  });
  
  page.on('response', response => {
    if (response.url().includes('/api/')) {
      console.log('🟡 API Response:', response.status(), response.url());
    }
  });

  try {
    console.log('Opening fantasy page...');
    await page.goto('http://localhost:3001/fantasy');
    
    console.log('Waiting for page to load...');
    await page.waitForTimeout(3000);
    
    // Take a screenshot to see current state
    await page.screenshot({ path: 'fantasy-page-debug.png', fullPage: true });
    console.log('Screenshot saved as fantasy-page-debug.png');
    
    // Check if we see login page or fantasy content
    const loginButton = page.locator('text="Log In"');
    const hasLogin = await loginButton.count() > 0;
    
    if (hasLogin) {
      console.log('❌ User needs to log in first - showing login page');
      console.log('Please log in through Google OAuth manually in the browser, then press Enter to continue...');
      
      // Wait for user to manually log in
      await new Promise(resolve => {
        process.stdin.once('data', resolve);
      });
      
      // Refresh page after login
      await page.reload();
      await page.waitForTimeout(3000);
    }
    
    // Now check for Player Compare button
    const compareButton = page.locator('text="Player Compare"');
    const compareCount = await compareButton.count();
    
    console.log(`Found ${compareCount} Player Compare buttons`);
    
    if (compareCount > 0) {
      console.log('✅ Found Player Compare button, clicking...');
      await compareButton.click();
      await page.waitForTimeout(2000);
      
      // Check if player search interface appeared
      const searchInput = page.locator('input[placeholder*="search" i], input[placeholder*="player" i]');
      const searchCount = await searchInput.count();
      console.log(`Found ${searchCount} search inputs`);
      
      if (searchCount > 0) {
        console.log('✅ Player search interface appeared');
        
        // Try to search for some test players
        await searchInput.first().fill('josh allen');
        await page.waitForTimeout(2000);
        
        // Look for search results
        const playerResults = page.locator('[data-testid*="player"], .player-result, [class*="player"]');
        const resultCount = await playerResults.count();
        console.log(`Found ${resultCount} potential player result elements`);
        
        if (resultCount >= 2) {
          console.log('✅ Found player results, selecting first 2...');
          
          // Try to find checkboxes
          const checkboxes = page.locator('input[type="checkbox"]');
          const checkboxCount = await checkboxes.count();
          console.log(`Found ${checkboxCount} checkboxes`);
          
          if (checkboxCount >= 2) {
            await checkboxes.nth(0).check();
            await checkboxes.nth(1).check();
            console.log('✅ Selected 2 players');
            
            // Look for Compare Players button
            const comparePlayersBtn = page.locator('text="Compare Players"');
            const compareBtnCount = await comparePlayersBtn.count();
            console.log(`Found ${compareBtnCount} "Compare Players" buttons`);
            
            if (compareBtnCount > 0) {
              console.log('🚀 Clicking Compare Players button...');
              await comparePlayersBtn.click();
              
              // Wait for API calls and response
              await page.waitForTimeout(5000);
              
              console.log('⏰ Waited 5 seconds for API response...');
              
              // Check for error messages
              const errorElements = page.locator('.text-red-800, [class*="error" i], [class*="Error"]');
              const errorCount = await errorElements.count();
              
              if (errorCount > 0) {
                console.log('❌ Found error messages:');
                for (let i = 0; i < errorCount; i++) {
                  const errorText = await errorElements.nth(i).textContent();
                  console.log(`  Error ${i + 1}: ${errorText}`);
                }
              } else {
                console.log('✅ No error messages found');
              }
              
              // Check for comparison results
              const comparisonContainer = page.locator('[class*="comparison"], [class*="compare"], [class*="result"]');
              const compCount = await comparisonContainer.count();
              console.log(`Found ${compCount} potential comparison result elements`);
            }
          }
        }
      }
    } else {
      console.log('❌ Player Compare button not found');
      
      // List available buttons
      const allButtons = page.locator('button');
      const btnCount = await allButtons.count();
      console.log(`Available buttons (${btnCount}):`);
      
      for (let i = 0; i < Math.min(btnCount, 20); i++) {
        const btnText = await allButtons.nth(i).textContent();
        console.log(`  ${i + 1}. "${btnText?.trim()}"`);
      }
    }
    
    console.log('Test completed. Press Enter to close browser...');
    await new Promise(resolve => {
      process.stdin.once('data', resolve);
    });
    
  } catch (error) {
    console.error('Test error:', error);
  }

  await browser.close();
}

debugPlayerCompare().catch(console.error);