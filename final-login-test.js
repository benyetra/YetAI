const { chromium } = require('playwright');

async function testFinalLoginFlow() {
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext();
  const page = await context.newPage();
  
  // Monitor network requests
  page.on('request', request => {
    if (request.url().includes('backend-production-f7af.up.railway.app')) {
      console.log(`→ ${request.method()} ${request.url()}`);
    }
  });
  
  page.on('response', response => {
    if (response.url().includes('backend-production-f7af.up.railway.app')) {
      console.log(`← ${response.status()} ${response.url()}`);
    }
  });
  
  page.on('console', msg => {
    if (msg.type() === 'error') {
      console.log(`CONSOLE ERROR: ${msg.text()}`);
    }
  });
  
  try {
    console.log('🔍 Testing final login flow with working backend...');
    
    // Go to login page
    await page.goto('https://yetai.app/login', { waitUntil: 'networkidle' });
    console.log('✅ Login page loaded');
    
    // Wait for form to be ready
    await page.waitForSelector('input[name="emailOrUsername"]', { timeout: 10000 });
    console.log('✅ Login form found');
    
    // Fill in credentials for our test user
    await page.fill('input[name="emailOrUsername"]', 'test2@example.com');
    await page.fill('input[name="password"]', 'testpassword123');
    console.log('✅ Credentials filled');
    
    // Take screenshot before login
    await page.screenshot({ path: '/tmp/before-final-login.png', fullPage: true });
    
    // Click login and wait for response
    const responsePromise = page.waitForResponse(response => 
      response.url().includes('/api/auth/login'), 
      { timeout: 15000 }
    );
    
    await page.click('button[type="submit"]');
    console.log('🚀 Login button clicked');
    
    const loginResponse = await responsePromise;
    console.log(`📡 Login response: ${loginResponse.status()}`);
    
    if (loginResponse.ok()) {
      const responseData = await loginResponse.json();
      console.log('📄 Response data:', JSON.stringify(responseData, null, 2));
      
      // Wait for redirect/page change
      await page.waitForTimeout(3000);
      
      const finalUrl = page.url();
      console.log(`🔍 Final URL: ${finalUrl}`);
      
      // Take final screenshot
      await page.screenshot({ path: '/tmp/after-final-login.png', fullPage: true });
      
      if (finalUrl.includes('dashboard')) {
        console.log('✅ SUCCESS! User was redirected to dashboard');
      } else {
        console.log('⚠️ User was not redirected to dashboard');
        
        // Check for any error messages
        const errors = await page.$$('.text-red-600, .text-red-800');
        if (errors.length > 0) {
          for (const error of errors) {
            const text = await error.textContent();
            console.log(`❌ Error: ${text}`);
          }
        }
      }
    } else {
      console.log(`❌ Login failed with status: ${loginResponse.status()}`);
    }
    
  } catch (error) {
    console.error('❌ Test failed:', error);
    await page.screenshot({ path: '/tmp/final-test-error.png', fullPage: true });
  }
  
  await browser.close();
}

testFinalLoginFlow().catch(console.error);