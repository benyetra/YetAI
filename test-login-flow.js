const { chromium } = require('playwright');

async function testUpdatedLoginFlow() {
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext();
  const page = await context.newPage();
  
  // Monitor requests and responses
  const networkLogs = [];
  
  page.on('request', request => {
    console.log(`→ ${request.method()} ${request.url()}`);
    networkLogs.push({type: 'request', method: request.method(), url: request.url()});
  });
  
  page.on('response', response => {
    console.log(`← ${response.status()} ${response.url()}`);
    networkLogs.push({type: 'response', status: response.status(), url: response.url()});
  });
  
  page.on('console', msg => {
    console.log(`CONSOLE ${msg.type()}: ${msg.text()}`);
  });
  
  page.on('pageerror', err => {
    console.error(`PAGE ERROR: ${err.message}`);
  });

  try {
    console.log('🔍 Testing updated login flow...');
    await page.goto('https://yetai.app/login', { waitUntil: 'networkidle' });
    
    console.log('📸 Taking screenshot of login page...');
    await page.screenshot({ path: '/tmp/updated-login.png', fullPage: true });
    
    // Wait for the form elements to be visible
    console.log('⏳ Waiting for form elements...');
    await page.waitForSelector('input[name="emailOrUsername"]', { timeout: 10000 });
    
    const emailInput = await page.$('input[name="emailOrUsername"]');
    const passwordInput = await page.$('input[name="password"]');
    const loginButton = await page.$('button[type="submit"]');
    
    console.log(`✅ Form elements found:`);
    console.log(`- Email input: ${emailInput ? 'YES' : 'NO'}`);
    console.log(`- Password input: ${passwordInput ? 'YES' : 'NO'}`);
    console.log(`- Login button: ${loginButton ? 'YES' : 'NO'}`);
    
    if (emailInput && passwordInput && loginButton) {
      console.log('🔑 Filling in test credentials...');
      
      await emailInput.fill('test@example.com');
      await passwordInput.fill('testpassword123');
      
      console.log('📸 Taking screenshot before login attempt...');
      await page.screenshot({ path: '/tmp/before-login-attempt.png', fullPage: true });
      
      // Click submit and watch for network activity
      console.log('🚀 Attempting login...');
      
      const responsePromise = page.waitForResponse(response => 
        response.url().includes('/api/auth/login'), 
        { timeout: 15000 }
      );
      
      await loginButton.click();
      
      try {
        const loginResponse = await responsePromise;
        console.log(`📡 Login API response: ${loginResponse.status()}`);
        
        const responseData = await loginResponse.json();
        console.log('📄 Response data:', JSON.stringify(responseData, null, 2));
        
        if (loginResponse.ok() && responseData.status === 'success') {
          console.log('✅ Login API call successful!');
        } else {
          console.log('❌ Login API call failed');
        }
      } catch (error) {
        console.log(`⏰ No login response received: ${error.message}`);
      }
      
      // Wait for any redirects or UI changes
      await page.waitForTimeout(5000);
      
      console.log('📸 Taking screenshot after login attempt...');
      await page.screenshot({ path: '/tmp/after-login-attempt.png', fullPage: true });
      
      const finalUrl = page.url();
      console.log(`🔍 Final URL: ${finalUrl}`);
      
      // Check for error messages
      const errorMessages = await page.$$('.text-red-600, .bg-red-50, .text-red-800, [role="alert"]');
      if (errorMessages.length > 0) {
        console.log('❌ Error messages found:');
        for (const error of errorMessages) {
          const text = await error.textContent();
          if (text && text.trim()) {
            console.log(`  - ${text.trim()}`);
          }
        }
      }
      
      // Check if we got redirected to dashboard
      if (finalUrl.includes('dashboard')) {
        console.log('✅ Successfully redirected to dashboard!');
      } else if (finalUrl.includes('login')) {
        console.log('⚠️ Still on login page');
      }
      
    } else {
      console.log('❌ Could not find all required form elements');
    }
    
  } catch (error) {
    console.error('❌ Test failed:', error);
    await page.screenshot({ path: '/tmp/test-error.png', fullPage: true });
  }
  
  // Network summary
  console.log('\n📊 Network Summary:');
  const apiCalls = networkLogs.filter(log => 
    log.url.includes('backend-production-f7af.up.railway.app')
  );
  
  console.log(`Backend API calls: ${apiCalls.length}`);
  apiCalls.forEach(call => {
    if (call.type === 'request') {
      console.log(`  → ${call.method} ${call.url}`);
    } else {
      console.log(`  ← ${call.status} ${call.url}`);
    }
  });
  
  await browser.close();
}

testUpdatedLoginFlow().catch(console.error);