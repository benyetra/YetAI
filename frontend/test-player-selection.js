const { chromium } = require('@playwright/test');

async function testPlayerSelection() {
  const browser = await chromium.launch({ headless: false, devtools: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  // Log all console messages to see our debug logs
  page.on('console', msg => {
    const text = msg.text();
    // Focus on our specific debug logs
    if (text.includes('handlePlayerSelect') || 
        text.includes('handleCompareSelected') || 
        text.includes('selectedPlayers') ||
        text.includes('Compare') ||
        text.includes('player(s) selected')) {
      console.log(`🔍 [${msg.type().toUpperCase()}] ${text}`);
    }
  });
  
  page.on('pageerror', error => {
    console.log('❌ JavaScript Error:', error.message);
  });

  try {
    console.log('📱 Opening fantasy page...');
    await page.goto('http://localhost:3001/fantasy');
    
    console.log('⏳ Waiting for page to load...');
    await page.waitForTimeout(3000);
    
    // Check if we need to log in
    const loginButton = page.locator('text="Log In"');
    const hasLogin = await loginButton.count() > 0;
    
    if (hasLogin) {
      console.log('🔐 Login required. Please log in manually and press Enter to continue...');
      await new Promise(resolve => {
        process.stdin.once('data', resolve);
      });
      await page.reload();
      await page.waitForTimeout(3000);
    }
    
    // Look for Player Compare button first
    const playerCompareBtn = page.locator('text="Player Compare"');
    const playerCompareBtnCount = await playerCompareBtn.count();
    
    console.log(`🔎 Found ${playerCompareBtnCount} "Player Compare" buttons`);
    
    if (playerCompareBtnCount > 0) {
      console.log('✅ Clicking Player Compare button...');
      await playerCompareBtn.click();
      await page.waitForTimeout(2000);
      
      // Now look for search interface
      console.log('🔍 Looking for search interface...');
      
      // Check if there's a search input
      const searchInputs = page.locator('input[type="text"], input[type="search"], input[placeholder*="search" i]');
      const searchCount = await searchInputs.count();
      console.log(`📝 Found ${searchCount} search inputs`);
      
      if (searchCount > 0) {
        console.log('🔎 Performing player search...');
        await searchInputs.first().fill('josh allen');
        await searchInputs.first().press('Enter');
        await page.waitForTimeout(3000);
        
        // Look for player checkboxes
        const checkboxes = page.locator('input[type="checkbox"]');
        const checkboxCount = await checkboxes.count();
        console.log(`☑️ Found ${checkboxCount} checkboxes`);
        
        if (checkboxCount >= 2) {
          console.log('✅ Selecting first 2 players...');
          
          console.log('📌 Clicking first checkbox...');
          await checkboxes.nth(0).click();
          await page.waitForTimeout(1000);
          
          console.log('📌 Clicking second checkbox...');
          await checkboxes.nth(1).click();
          await page.waitForTimeout(1000);
          
          // Check if selection count updated
          const selectionText = page.locator('text=/\\d+ player\\(s\\) selected/');
          const selectionCount = await selectionText.count();
          
          if (selectionCount > 0) {
            const selectionMessage = await selectionText.textContent();
            console.log(`✅ Selection updated: ${selectionMessage}`);
            
            // Look for Compare Players button
            const comparePlayersBtn = page.locator('text="Compare Players"');
            const compareBtnCount = await comparePlayersBtn.count();
            console.log(`🎯 Found ${compareBtnCount} "Compare Players" buttons`);
            
            if (compareBtnCount > 0) {
              console.log('🚀 About to click "Compare Players" button...');
              console.log('👂 Listening for handleCompareSelected logs...');
              
              await comparePlayersBtn.click();
              
              console.log('⏰ Waiting 3 seconds to see if function was called...');
              await page.waitForTimeout(3000);
              
              console.log('✅ Button click completed');
            } else {
              console.log('❌ "Compare Players" button not found after player selection');
            }
          } else {
            console.log('❌ Player selection count not updated - checkboxes may not be working');
          }
        } else {
          console.log('❌ Not enough checkboxes found for testing');
        }
      } else {
        console.log('❌ No search input found');
      }
    } else {
      console.log('❌ "Player Compare" button not found');
      
      // Show available buttons for debugging
      const allButtons = page.locator('button');
      const btnCount = await allButtons.count();
      console.log(`🔍 Available buttons (${btnCount}):`);
      
      for (let i = 0; i < Math.min(btnCount, 10); i++) {
        const btnText = await allButtons.nth(i).textContent();
        console.log(`  ${i + 1}. "${btnText?.trim()}"`);
      }
    }
    
    console.log('✅ Test completed. Press Enter to close browser...');
    await new Promise(resolve => {
      process.stdin.once('data', resolve);
    });
    
  } catch (error) {
    console.error('❌ Test error:', error);
  }

  await browser.close();
}

testPlayerSelection().catch(console.error);