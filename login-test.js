const { chromium } = require('playwright');

async function testLoginFlow() {
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext();
  const page = await context.newPage();
  
  // Monitor network requests
  const networkLogs = [];
  
  page.on('request', request => {
    const log = {
      type: 'request',
      url: request.url(),
      method: request.method(),
      timestamp: new Date().toISOString()
    };
    networkLogs.push(log);
    console.log(`→ ${request.method()} ${request.url()}`);
  });
  
  page.on('response', response => {
    const log = {
      type: 'response',
      url: response.url(),
      status: response.status(),
      statusText: response.statusText(),
      timestamp: new Date().toISOString()
    };
    networkLogs.push(log);
    console.log(`← ${response.status()} ${response.url()}`);
  });
  
  // Monitor console messages and errors
  page.on('console', msg => {
    console.log(`CONSOLE ${msg.type()}: ${msg.text()}`);
  });
  
  page.on('pageerror', err => {
    console.error(`PAGE ERROR: ${err.message}`);
  });

  try {
    console.log('🔍 Testing login flow...');
    await page.goto('https://yetai.app/login', { waitUntil: 'networkidle' });
    
    console.log('📸 Taking screenshot of login page...');
    await page.screenshot({ path: '/tmp/login-initial.png', fullPage: true });
    
    // Check if login form is present
    const emailInput = await page.waitForSelector('input[type="email"], input[name="email"], input[placeholder*="email"], input[placeholder*="Email"]', { timeout: 5000 });
    const passwordInput = await page.waitForSelector('input[type="password"], input[name="password"], input[placeholder*="password"]', { timeout: 5000 });
    const loginButton = await page.waitForSelector('button:has-text("Log In"), button[type="submit"]', { timeout: 5000 });
    
    console.log('✅ Login form elements found');
    
    // Check if there are any existing test users by trying a test login
    console.log('🔑 Testing with test credentials...');
    
    await emailInput.fill('test@example.com');
    await passwordInput.fill('testpassword');
    
    console.log('📸 Taking screenshot before login attempt...');
    await page.screenshot({ path: '/tmp/login-before-submit.png', fullPage: true });
    
    // Monitor network traffic during login
    const loginPromise = page.waitForResponse(response => 
      response.url().includes('login') || response.url().includes('auth'), 
      { timeout: 10000 }
    );
    
    await loginButton.click();
    
    try {
      const response = await loginPromise;
      console.log(`📡 Login response: ${response.status()} ${response.url()}`);
      
      if (response.ok()) {
        const responseBody = await response.text();
        console.log(`✅ Login response body: ${responseBody.substring(0, 200)}...`);
      } else {
        console.log(`❌ Login failed with status: ${response.status()}`);
      }
    } catch (error) {
      console.log('⏰ No login response received within timeout');
    }
    
    // Wait and check what happened
    await page.waitForTimeout(3000);
    
    console.log('📸 Taking screenshot after login attempt...');
    await page.screenshot({ path: '/tmp/login-after-submit.png', fullPage: true });
    
    const currentUrl = page.url();
    console.log(`🔍 Current URL: ${currentUrl}`);
    
    // Check for error messages
    const errorElements = await page.$$('.error, .alert, [role="alert"], .text-red-500, .text-danger');
    if (errorElements.length > 0) {
      console.log('❌ Error messages found:');
      for (const element of errorElements) {
        const text = await element.textContent();
        if (text && text.trim()) {
          console.log(`  - ${text.trim()}`);
        }
      }
    }
    
    // Check if we were redirected to dashboard or if we're still on login page
    if (currentUrl.includes('dashboard')) {
      console.log('✅ Successfully redirected to dashboard!');
    } else if (currentUrl.includes('login')) {
      console.log('⚠️ Still on login page - likely authentication failed');
    } else {
      console.log(`🔄 Redirected to: ${currentUrl}`);
    }
    
    // Test direct API call
    console.log('🔍 Testing direct API authentication...');
    try {
      const apiResponse = await page.request.post('https://backend-production-f7af.up.railway.app/auth/login', {
        data: {
          email: 'test@example.com',
          password: 'testpassword'
        },
        headers: {
          'Content-Type': 'application/json'
        }
      });
      
      console.log(`📡 Direct API login: ${apiResponse.status()}`);
      if (apiResponse.ok()) {
        const apiBody = await apiResponse.json();
        console.log('✅ Direct API login successful:', JSON.stringify(apiBody, null, 2));
      } else {
        const errorText = await apiResponse.text();
        console.log(`❌ Direct API login failed: ${errorText}`);
      }
    } catch (apiError) {
      console.log(`❌ Direct API call failed: ${apiError.message}`);
    }
    
  } catch (error) {
    console.error('❌ Test failed:', error);
    await page.screenshot({ path: '/tmp/login-error.png', fullPage: true });
  }
  
  // Network summary
  console.log('\n📊 Network Activity Summary:');
  const requests = networkLogs.filter(log => log.type === 'request');
  const responses = networkLogs.filter(log => log.type === 'response');
  
  console.log(`Total requests: ${requests.length}`);
  console.log(`Total responses: ${responses.length}`);
  
  const failedResponses = responses.filter(r => r.status >= 400);
  if (failedResponses.length > 0) {
    console.log('\n❌ Failed requests:');
    failedResponses.forEach(r => {
      console.log(`  ${r.status} ${r.url}`);
    });
  }
  
  const authRequests = requests.filter(r => 
    r.url.includes('auth') || 
    r.url.includes('login') ||
    r.url.includes('backend-production-f7af.up.railway.app')
  );
  console.log(`\n🔐 Authentication-related requests: ${authRequests.length}`);
  authRequests.forEach(req => {
    console.log(`  ${req.method} ${req.url}`);
  });
  
  await browser.close();
}

testLoginFlow().catch(console.error);