const { chromium } = require('playwright');

async function testTradeValues() {
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();
  
  try {
    console.log('Navigating to trade analyzer...');
    await page.goto('http://localhost:3002/fantasy');
    
    // Wait for the page to load
    await page.waitForTimeout(3000);
    
    // Look for the trade analyzer section
    await page.waitForSelector('[data-testid="trade-analyzer"], .trade-analyzer, h3:has-text("Build Custom Trade")', { timeout: 10000 });
    
    console.log('Trade analyzer loaded, checking for player values...');
    
    // Look for any player cards that show trade values
    const playerValues = await page.locator('text=/\\d+\\.\\d+/').allTextContents();
    console.log('Found player values:', playerValues);
    
    // Check if we see values other than 10.0
    const nonTenValues = playerValues.filter(val => !val.includes('10.0') && !val.includes('10'));
    console.log('Non-10.0 values found:', nonTenValues);
    
    if (nonTenValues.length > 0) {
      console.log('✅ SUCCESS: Dynamic trade values are working!');
    } else {
      console.log('❌ ISSUE: Still seeing 10.0 values');
    }
    
  } catch (error) {
    console.error('Test failed:', error);
  } finally {
    await browser.close();
  }
}

testTradeValues();