# YetAI Backend Deployment - Action Plan

## Current Status (2025-10-10 17:58 EDT)

- ✅ **Deployment infrastructure fixed and committed** (commit: 21adb733)
- ✅ **Code pushed to GitHub main branch**
- 🔄 **GitHub Actions workflow running** (in progress)
- 🔄 **Railway deploying new version** (HTTP 502 - deployment in progress)
- ⏳ **Waiting for deployment to complete** (estimated 3-5 minutes)

## Immediate Actions (Next 10 Minutes)

### 1. Monitor GitHub Actions Workflow
```bash
# Check workflow status
gh run list --limit 1

# View workflow in browser
gh run view 18419299561 --web

# Or visit directly:
# https://github.com/benyetra/YetAI/actions/runs/18419299561
```

**Expected outcome:**
- Test job: PASS
- Security scan job: PASS
- Validate deployment job: PASS (after Railway deploys)

### 2. Monitor Railway Deployment

**Option A - Railway CLI:**
```bash
# Install Railway CLI (if not installed)
npm install -g @railway/cli

# View logs
railway logs --tail 100

# Check deployment status
railway status
```

**Option B - Railway Dashboard:**
- Go to https://railway.app
- Select YetAI project
- Click on backend service
- View deployment logs and status

**Expected outcome:**
- Build completes successfully
- Container starts and binds to PORT
- Health check at /health passes
- Status shows "Active"

### 3. Run Monitoring Script

Once deployment is complete (GitHub Actions validation job passes):

```bash
# Run continuous monitoring for 5 minutes
cd /Users/byetz/Development/YetAI/YetAI
bash backend/scripts/monitor_deployment.sh
```

**Expected outcome:**
- Health checks return HTTP 200
- All endpoints responding correctly
- No consecutive failures

## Critical Action (Must Do Before Testing Email)

### Update SMTP_USER Environment Variable

**IMPORTANT**: The email verification system will NOT work until this is updated.

**Follow these steps:**

1. **Open Railway Dashboard**
   - Go to https://railway.app
   - Login to your account
   - Select "YetAI" project
   - Click on "backend" service

2. **Update Environment Variable**
   - Click "Variables" tab
   - Find `SMTP_USER`
   - **Current value**: `yetai.help@gmail.com` ❌
   - **Change to**: `9901af001@smtp-brevo.com` ✅
   - Save the change

3. **Trigger Redeploy (if needed)**
   - Railway may auto-redeploy after variable change
   - If not, click "Redeploy" button
   - Wait 2-3 minutes for deployment

4. **Verify Update**
   ```bash
   # Check Railway logs for SMTP connection
   railway logs | grep -i smtp

   # Should see: Using SMTP user: 9901af001@smtp-brevo.com
   ```

**Detailed instructions**: See `/Users/byetz/Development/YetAI/YetAI/RAILWAY_ENV_UPDATE.md`

## Validation Testing (After Deployment Completes)

### 1. Basic Health Checks

```bash
# Health endpoint
curl https://api.yetai.app/health

# Expected: {"status":"healthy","timestamp":"...","database":"connected"}

# API status
curl https://api.yetai.app/api/status

# Database connection
curl https://api.yetai.app/test-db
```

### 2. Test Registration Endpoint (Latest Fix)

```bash
# Test with Pydantic UserSignup model
curl -X POST https://api.yetai.app/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "username": "testuser",
    "password": "SecurePass123",
    "first_name": "Test",
    "last_name": "User"
  }' \
  -w "\nHTTP Status: %{http_code}\n"
```

**Expected response:**
- HTTP Status: 201
- JSON with user object
- `is_verified: false`
- Message about checking email

### 3. Test Email Verification (After SMTP_USER Update)

```bash
# Register with your real email
curl -X POST https://api.yetai.app/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "your-real-email@example.com",
    "username": "yourname",
    "password": "SecurePassword123!",
    "first_name": "Your",
    "last_name": "Name"
  }'
```

**Then:**
1. Check your email inbox
2. Look for verification email from `yetai.help@gmail.com`
3. Click the verification link
4. Verify user is activated
5. Test login with verified user

### 4. Run Comprehensive Validation

```bash
# Automated validation script
cd /Users/byetz/Development/YetAI/YetAI
bash backend/scripts/validate_deployment.sh https://api.yetai.app
```

**Expected outcome:**
- All 5 endpoint tests pass
- CORS headers present
- No errors or timeouts

## Troubleshooting

### If Deployment Fails

**Check GitHub Actions logs:**
```bash
# View latest run
gh run view --log-failed

# Common issues:
# - Linting errors (fix code style)
# - Test failures (fix failing tests)
# - Security vulnerabilities (update dependencies)
```

**Check Railway deployment logs:**
```bash
railway logs

# Common issues:
# - PORT binding failure (check Dockerfile CMD)
# - Database connection failed (check DATABASE_URL)
# - Missing dependencies (check requirements.txt)
# - Health check timeout (check /health endpoint)
```

### If API Returns 502 for More Than 10 Minutes

1. **Check Railway Dashboard**
   - Look for build errors
   - Check container status
   - Verify health checks

2. **Check Application Logs**
   ```bash
   railway logs --tail 100
   ```

3. **Consider Rollback**
   ```bash
   # Option 1: Railway Dashboard
   # Go to Deployments > Select previous working deployment > Redeploy

   # Option 2: Git revert
   git revert 21adb733
   git push origin main
   ```

### If Email Verification Doesn't Work

1. **Verify SMTP_USER was updated**
   - Should be: `9901af001@smtp-brevo.com`
   - Not: `yetai.help@gmail.com`

2. **Check Railway environment variables**
   ```bash
   railway variables
   ```

3. **Check application logs for email errors**
   ```bash
   railway logs | grep -i "email\|smtp"
   ```

4. **Test SMTP connection manually**
   - See RAILWAY_ENV_UPDATE.md for testing instructions

## Success Criteria Checklist

After completing all actions, verify:

- [ ] GitHub Actions workflow completed successfully
- [ ] Railway deployment status shows "Active"
- [ ] Health endpoint returns HTTP 200
- [ ] API status endpoint responding
- [ ] Database connection working
- [ ] Chat suggestions endpoint working
- [ ] Registration endpoint returns HTTP 201
- [ ] SMTP_USER updated to Brevo username
- [ ] Email verification email received
- [ ] Verification link works
- [ ] User can login after verification
- [ ] No errors in Railway logs
- [ ] Response times < 500ms

## Timeline Estimate

| Task | Duration | Status |
|------|----------|--------|
| GitHub Actions workflow | 3-5 min | 🔄 In progress |
| Railway deployment | 3-5 min | 🔄 In progress |
| Initial validation | 2 min | ⏳ Pending |
| Update SMTP_USER | 5 min | ⏳ **ACTION REQUIRED** |
| Test email verification | 5 min | ⏳ Pending |
| Final validation | 5 min | ⏳ Pending |
| **Total** | **20-30 min** | |

## Quick Reference Links

### GitHub
- **Actions Workflow**: https://github.com/benyetra/YetAI/actions/runs/18419299561
- **Repository**: https://github.com/benyetra/YetAI
- **Commit**: https://github.com/benyetra/YetAI/commit/21adb733

### Railway
- **Dashboard**: https://railway.app
- **Docs**: https://docs.railway.app
- **Status**: https://status.railway.app

### API Endpoints
- **Health**: https://api.yetai.app/health
- **Status**: https://api.yetai.app/api/status
- **Database**: https://api.yetai.app/test-db
- **Register**: https://api.yetai.app/api/auth/register

### Documentation
- **Deployment Guide**: `/Users/byetz/Development/YetAI/YetAI/RAILWAY_DEPLOYMENT.md`
- **Quick Start**: `/Users/byetz/Development/YetAI/YetAI/DEPLOYMENT_QUICKSTART.md`
- **SMTP Update**: `/Users/byetz/Development/YetAI/YetAI/RAILWAY_ENV_UPDATE.md`
- **Full Summary**: `/Users/byetz/Development/YetAI/YetAI/DEPLOYMENT_SUMMARY.md`

## Next Steps After Success

1. **Document Results**
   - Note any issues encountered
   - Update troubleshooting guides if needed
   - Share success with team

2. **Set Up Monitoring**
   - Configure Railway alerts
   - Set up uptime monitoring (e.g., UptimeRobot)
   - Create dashboard for key metrics

3. **Plan Future Improvements**
   - Consider staging environment
   - Implement database migrations automation
   - Add performance monitoring (New Relic, Datadog)
   - Set up error tracking (Sentry)

4. **Security Hardening**
   - Rotate secrets regularly
   - Enable 2FA on all services
   - Review and update dependencies
   - Implement rate limiting

---

**Created**: 2025-10-10 17:58 EDT
**Deployment Commit**: 21adb733
**Status**: Deployment in progress, monitoring required
**Next Action**: Monitor GitHub Actions and Railway deployment, then update SMTP_USER
