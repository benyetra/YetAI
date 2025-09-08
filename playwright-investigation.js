const { chromium } = require('playwright');

async function investigateLoginFlow() {
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext();
  const page = await context.newPage();
  
  // Set up network monitoring
  const requests = [];
  const responses = [];
  
  page.on('request', request => {
    requests.push({
      url: request.url(),
      method: request.method(),
      headers: request.headers(),
      timestamp: new Date().toISOString()
    });
    console.log(`→ ${request.method()} ${request.url()}`);
  });
  
  page.on('response', response => {
    responses.push({
      url: response.url(),
      status: response.status(),
      statusText: response.statusText(),
      timestamp: new Date().toISOString()
    });
    console.log(`← ${response.status()} ${response.url()}`);
  });
  
  // Listen for console logs and errors
  page.on('console', msg => {
    console.log(`CONSOLE ${msg.type()}: ${msg.text()}`);
  });
  
  page.on('pageerror', err => {
    console.error(`PAGE ERROR: ${err.message}`);
  });

  try {
    console.log('🔍 Navigating to https://yetai.app...');
    await page.goto('https://yetai.app', { waitUntil: 'networkidle' });
    
    console.log('📸 Taking screenshot of landing page...');
    await page.screenshot({ path: '/tmp/yetai-landing.png', fullPage: true });
    
    console.log('🔍 Looking for login elements...');
    
    // Check if we're already on a login page or if there's a login link
    const currentUrl = page.url();
    console.log(`Current URL: ${currentUrl}`);
    
    const loginButtons = await page.$$('[data-testid*="login"], a[href*="login"], button:has-text("Login"), button:has-text("Sign In"), a:has-text("Login"), a:has-text("Sign In")');
    console.log(`Found ${loginButtons.length} potential login elements`);
    
    if (loginButtons.length > 0) {
      console.log('🔽 Clicking login button...');
      await loginButtons[0].click();
      await page.waitForTimeout(2000);
    } else {
      // Try navigating directly to login page
      console.log('🔍 Trying direct navigation to /login...');
      await page.goto('https://yetai.app/login', { waitUntil: 'networkidle' });
    }
    
    console.log('📸 Taking screenshot of login page...');
    await page.screenshot({ path: '/tmp/yetai-login.png', fullPage: true });
    
    // Look for login form elements
    const emailInput = await page.$('input[type="email"], input[name="email"], input[placeholder*="email"]');
    const passwordInput = await page.$('input[type="password"], input[name="password"], input[placeholder*="password"]');
    const submitButton = await page.$('button[type="submit"], button:has-text("Login"), button:has-text("Sign In")');
    
    console.log(`Login form elements found:`);
    console.log(`- Email input: ${emailInput ? 'YES' : 'NO'}`);
    console.log(`- Password input: ${passwordInput ? 'YES' : 'NO'}`);
    console.log(`- Submit button: ${submitButton ? 'YES' : 'NO'}`);
    
    if (emailInput && passwordInput && submitButton) {
      console.log('🔑 Testing login with test credentials...');
      
      // Try to login with test credentials
      await emailInput.fill('test@example.com');
      await passwordInput.fill('testpassword');
      
      console.log('📸 Taking screenshot before login attempt...');
      await page.screenshot({ path: '/tmp/yetai-before-login.png', fullPage: true });
      
      // Click submit and wait for response
      await submitButton.click();
      
      // Wait a bit to see what happens
      await page.waitForTimeout(5000);
      
      console.log('📸 Taking screenshot after login attempt...');
      await page.screenshot({ path: '/tmp/yetai-after-login.png', fullPage: true });
      
      const finalUrl = page.url();
      console.log(`Final URL after login attempt: ${finalUrl}`);
      
      // Check for any error messages
      const errorMessages = await page.$$('.error, .alert-danger, [role="alert"]');
      if (errorMessages.length > 0) {
        for (const error of errorMessages) {
          const text = await error.textContent();
          console.log(`❌ Error message found: ${text}`);
        }
      }
    }
    
    // Test API endpoint directly
    console.log('🔍 Testing backend API endpoint...');
    const apiResponse = await page.request.get('https://backend-production-f7af.up.railway.app/health');
    console.log(`API Health Check: ${apiResponse.status()} ${apiResponse.statusText()}`);
    
    if (apiResponse.ok()) {
      const healthData = await apiResponse.json();
      console.log('✅ Backend API is responding:', healthData);
    } else {
      console.log('❌ Backend API health check failed');
    }
    
  } catch (error) {
    console.error('❌ Investigation failed:', error);
    await page.screenshot({ path: '/tmp/yetai-error.png', fullPage: true });
  }
  
  // Summary of network activity
  console.log('\n📊 Network Activity Summary:');
  console.log(`Total requests: ${requests.length}`);
  console.log(`Total responses: ${responses.length}`);
  
  // Check for failed requests
  const failedRequests = responses.filter(r => r.status >= 400);
  if (failedRequests.length > 0) {
    console.log('\n❌ Failed requests:');
    failedRequests.forEach(r => {
      console.log(`  ${r.status} ${r.url}`);
    });
  }
  
  // Check for backend API calls
  const backendCalls = requests.filter(r => r.url.includes('backend-production-f7af.up.railway.app'));
  console.log(`\n🔗 Backend API calls: ${backendCalls.length}`);
  backendCalls.forEach(call => {
    console.log(`  ${call.method} ${call.url}`);
  });
  
  await browser.close();
}

// Run the investigation
investigateLoginFlow().catch(console.error);