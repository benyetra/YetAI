const { chromium } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

async function captureYetAIUI() {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 }
  });
  const page = await context.newPage();

  // Create screenshots directory
  const screenshotsDir = path.join(__dirname, 'ui-screenshots');
  if (!fs.existsSync(screenshotsDir)) {
    fs.mkdirSync(screenshotsDir);
  }

  console.log('Capturing YetAI app screenshots...');

  try {
    // Navigate to the app
    await page.goto('http://localhost:3001');
    
    // Wait for page to load
    await page.waitForTimeout(3000);
    
    // Capture homepage
    await page.screenshot({ 
      path: path.join(screenshotsDir, '01-homepage.png'),
      fullPage: true 
    });
    console.log('✓ Homepage captured');

    // Try to navigate to different sections
    const links = await page.$$('a[href]');
    const navigation = [];
    
    for (let i = 0; i < Math.min(links.length, 10); i++) {
      try {
        const href = await links[i].getAttribute('href');
        const text = await links[i].textContent();
        if (href && href.startsWith('/') && text) {
          navigation.push({ href, text: text.trim() });
        }
      } catch (e) {
        // Skip broken links
      }
    }

    console.log('Found navigation links:', navigation);

    // Capture navigation screenshots
    for (let i = 0; i < navigation.length; i++) {
      try {
        const nav = navigation[i];
        await page.goto(`http://localhost:3001${nav.href}`);
        await page.waitForTimeout(2000);
        
        const filename = `${String(i + 2).padStart(2, '0')}-${nav.text.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')}.png`;
        await page.screenshot({ 
          path: path.join(screenshotsDir, filename),
          fullPage: true 
        });
        console.log(`✓ ${nav.text} page captured`);
      } catch (error) {
        console.log(`⚠ Could not capture ${navigation[i].text}: ${error.message}`);
      }
    }

    // Try to capture any forms or interactive elements
    await page.goto('http://localhost:3001');
    await page.waitForTimeout(2000);
    
    // Look for buttons, forms, or interactive elements
    const buttons = await page.$$('button');
    const forms = await page.$$('form');
    const inputs = await page.$$('input');

    console.log(`Found ${buttons.length} buttons, ${forms.length} forms, ${inputs.length} inputs`);

  } catch (error) {
    console.error('Error capturing screenshots:', error);
  }

  await browser.close();
  console.log(`Screenshots saved to: ${screenshotsDir}`);
}

captureYetAIUI().catch(console.error);