# Railway Environment Variable Update Checklist

## CRITICAL: Update SMTP_USER Variable

### Current Issue
The SMTP_USER environment variable in Railway is set to the old Gmail address:
```
SMTP_USER="yetai.help@gmail.com"  ❌ WRONG
```

### Required Change
Update to the Brevo SMTP username:
```
SMTP_USER="9901af001@smtp-brevo.com"  ✅ CORRECT
```

## How to Update in Railway Dashboard

### Step-by-Step Instructions

1. **Log in to Railway**
   - Go to https://railway.app
   - Log in with your credentials

2. **Navigate to Project**
   - Select the "YetAI" project
   - Click on the "backend" service

3. **Open Variables Tab**
   - Click on the "Variables" tab
   - Find the "SMTP_USER" variable

4. **Update the Value**
   - Click on the "SMTP_USER" variable
   - Change value from `yetai.help@gmail.com` to `9901af001@smtp-brevo.com`
   - Click "Save" or press Enter

5. **Trigger Redeploy**
   - Railway will automatically redeploy with the new variable
   - OR click "Redeploy" button if auto-deploy doesn't trigger

6. **Wait for Deployment**
   - Watch the deployment logs
   - Wait for health check to pass
   - Should take 2-3 minutes

## Verify the Update

### Test Email Verification System

```bash
# 1. Register a new user
curl -X POST https://api.yetai.app/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "your-test-email@example.com",
    "username": "testuser123",
    "password": "SecurePass123!",
    "first_name": "Test",
    "last_name": "User"
  }'

# Expected response (HTTP 201):
# {
#   "message": "User registered successfully. Please check your email to verify your account.",
#   "user": {
#     "id": ...,
#     "email": "your-test-email@example.com",
#     "username": "testuser123",
#     "is_verified": false
#   }
# }

# 2. Check your email inbox
# - Look for verification email from yetai.help@gmail.com
# - Email should be sent via Brevo SMTP relay

# 3. Click verification link in email
# - Should redirect to success page
# - User should be marked as verified in database

# 4. Verify user can now login
curl -X POST https://api.yetai.app/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email_or_username": "testuser123",
    "password": "SecurePass123!"
  }'

# Expected response (HTTP 200):
# {
#   "access_token": "...",
#   "token_type": "bearer",
#   "user": { ... }
# }
```

## Complete Environment Variables Reference

Verify all these are set correctly in Railway:

```bash
# Email Configuration (Brevo SMTP)
SMTP_HOST="smtp-relay.brevo.com"
SMTP_PORT="587"
SMTP_USER="9901af001@smtp-brevo.com"  # ← UPDATE THIS!
SMTP_PASSWORD="swzM8yBHR7VZAh6j"
FROM_EMAIL="yetai.help@gmail.com"

# Database (Auto-set by Railway PostgreSQL)
DATABASE_URL="postgresql://..."  # Set by Railway

# Application
PORT="8000"  # Set by Railway (may be different)
ENVIRONMENT="production"
SECRET_KEY="your-secret-key-here"

# Optional - AI Features
OPENAI_API_KEY="sk-..."  # If using AI features

# Optional - Payment Processing
STRIPE_API_KEY="sk_..."  # If using Stripe
STRIPE_WEBHOOK_SECRET="whsec_..."  # If using Stripe webhooks
```

## Troubleshooting

### Email Not Sending After Update

1. **Check Railway Logs**
   ```bash
   railway logs
   # Look for SMTP connection errors
   ```

2. **Verify SMTP Credentials**
   - SMTP_USER: `9901af001@smtp-brevo.com`
   - SMTP_PASSWORD: `swzM8yBHR7VZAh6j`
   - SMTP_HOST: `smtp-relay.brevo.com`
   - SMTP_PORT: `587`

3. **Test SMTP Connection Manually**
   ```python
   import smtplib

   smtp = smtplib.SMTP('smtp-relay.brevo.com', 587)
   smtp.starttls()
   smtp.login('9901af001@smtp-brevo.com', 'swzM8yBHR7VZAh6j')
   smtp.quit()
   print("SMTP connection successful!")
   ```

4. **Check Brevo Dashboard**
   - Go to https://app.brevo.com
   - Check SMTP & API > SMTP settings
   - Verify credentials match
   - Check sending quota and limits

### Deployment Failed After Update

1. **Check Railway deployment logs**
   - Look for startup errors
   - Verify environment variable is set

2. **Rollback if needed**
   - Railway keeps previous deployment running
   - Click "Redeploy" on previous working deployment

3. **Verify variable syntax**
   - No quotes around value in Railway UI
   - Just: `9901af001@smtp-brevo.com`
   - Not: `"9901af001@smtp-brevo.com"`

## Success Criteria

After updating SMTP_USER, you should see:

- ✅ Deployment successful with no errors
- ✅ Health check passing
- ✅ New user registration returns 201 status
- ✅ Verification email received in inbox
- ✅ Email sent via Brevo (check email headers)
- ✅ Verification link works
- ✅ User can login after verification

## Monitoring

### Railway Metrics to Watch
- Deployment status: Should be "Active"
- Health checks: Should be passing
- Logs: No SMTP authentication errors
- Response times: Should be < 500ms

### Application Logs to Check
```bash
# View recent logs
railway logs --tail 100

# Look for:
# ✅ "Email sent successfully to user@example.com"
# ❌ "SMTP authentication failed"
# ❌ "Connection to SMTP server failed"
```

## Next Steps After Update

1. ✅ Update SMTP_USER variable in Railway
2. ✅ Wait for automatic redeploy
3. ✅ Test registration with real email
4. ✅ Verify email is received
5. ✅ Test verification link
6. ✅ Confirm user can login
7. 📝 Document any issues encountered
8. 🎉 Email verification system is working!

---

Last updated: 2025-10-10
Railway Dashboard: https://railway.app
Brevo Dashboard: https://app.brevo.com
