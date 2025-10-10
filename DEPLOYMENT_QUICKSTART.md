# YetAI Backend Deployment - Quick Start Guide

## TL;DR - How to Deploy

### Automatic Deployment (Normal Flow)
```bash
# 1. Make your changes
git add .
git commit -m "Your commit message"
git push origin main

# 2. Railway automatically deploys
# 3. GitHub Actions validates deployment
# 4. Done!
```

## What Happens When You Push to Main

```
1. GitHub receives push
   |
2. GitHub Actions runs:
   - Linting & code quality checks
   - Security scanning (Bandit, Safety)
   - Unit tests with coverage
   |
3. Railway auto-deploys:
   - Detects push to main branch
   - Builds Docker image from backend/Dockerfile
   - Runs health check on /health endpoint
   - Switches traffic to new deployment
   |
4. GitHub Actions validates:
   - Waits 90s for deployment
   - Runs comprehensive validation script
   - Tests all critical endpoints
   - Tests registration endpoint (latest fix)
   |
5. Success! New code is live
```

## Check Deployment Status

### Railway Dashboard
1. Go to https://railway.app
2. Select your project
3. View deployment logs and status

### Railway CLI
```bash
# View logs
railway logs

# Check status
railway status

# Open service in browser
railway open
```

### GitHub Actions
1. Go to https://github.com/benyetra/YetAI/actions
2. Click on latest workflow run
3. View deployment validation results

## Manual Health Check

```bash
# Health endpoint
curl https://api.yetai.app/health

# Expected response:
# {"status":"healthy","timestamp":"...","database":"connected"}

# API status
curl https://api.yetai.app/api/status

# Database connection
curl https://api.yetai.app/test-db
```

## Environment Variables to Update

CRITICAL - Update in Railway dashboard:

```bash
SMTP_USER="9901af001@smtp-brevo.com"  # Change from yetai.help@gmail.com
```

Other variables (already set):
```bash
SMTP_HOST="smtp-relay.brevo.com"
SMTP_PORT="587"
SMTP_PASSWORD="swzM8yBHR7VZAh6j"
FROM_EMAIL="yetai.help@gmail.com"
DATABASE_URL=[auto-set by Railway]
PORT=[auto-set by Railway]
```

## Test Email Verification

After updating SMTP_USER:

```bash
# 1. Register a new user
curl -X POST https://api.yetai.app/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "your-email@example.com",
    "username": "testuser",
    "password": "SecurePass123",
    "first_name": "Test",
    "last_name": "User"
  }'

# 2. Check your email for verification link
# 3. Click verification link
# 4. Verify user is activated in database
```

## Troubleshooting

### Deployment Failed
1. Check Railway logs: `railway logs`
2. Check GitHub Actions workflow
3. Look for PORT binding errors
4. Verify environment variables

### Old Code Running
This is now FIXED! The issue was:
- Multiple conflicting config files (railway.toml, root Dockerfile, etc.)
- Now we have single source of truth: railway.json
- Points to backend/Dockerfile explicitly

### Health Check Failing
```bash
# Check if service is running
curl https://api.yetai.app/health

# Check Railway dashboard for errors
railway logs

# Common causes:
# - Database connection failed
# - PORT not binding correctly
# - Application crash on startup
```

### Email Not Sending
1. Verify SMTP_USER is updated to `9901af001@smtp-brevo.com`
2. Check Railway environment variables
3. Test SMTP credentials
4. Check application logs for email errors

## Rollback Process

### Automatic Rollback
Railway keeps previous deployment running if new one fails.

### Manual Rollback
```bash
# Option 1: Railway Dashboard
# 1. Go to Deployments tab
# 2. Find working deployment
# 3. Click "Redeploy"

# Option 2: Git Revert
git revert <bad-commit-hash>
git push origin main
```

## Key Files

### Deployment Configuration
- `/railway.json` - Railway deployment config (SINGLE SOURCE OF TRUTH)
- `/backend/Dockerfile` - Production Docker image

### CI/CD
- `/.github/workflows/backend-ci-cd.yml` - GitHub Actions pipeline

### Validation
- `/backend/scripts/validate_deployment.sh` - Deployment validation script

### Documentation
- `/RAILWAY_DEPLOYMENT.md` - Comprehensive deployment guide
- `/DEPLOYMENT_QUICKSTART.md` - This file

## Deployment Checklist

Before deploying important changes:

- [ ] Tests passing locally
- [ ] Code linted and formatted
- [ ] Environment variables configured
- [ ] Database migrations ready (if needed)
- [ ] Breaking changes documented
- [ ] Rollback plan ready

After deployment:

- [ ] Health check passing
- [ ] Critical endpoints tested
- [ ] Database connections working
- [ ] Email system functional
- [ ] No errors in logs
- [ ] Performance metrics normal

## Getting Help

### Railway Issues
- Railway Docs: https://docs.railway.app
- Railway Discord: https://discord.gg/railway
- Railway Status: https://status.railway.app

### Application Issues
- GitHub Issues: https://github.com/benyetra/YetAI/issues
- Check application logs: `railway logs`
- Review GitHub Actions runs

## Next Steps

1. **Update SMTP_USER**: Change to `9901af001@smtp-brevo.com` in Railway
2. **Test deployment**: Push this commit and monitor
3. **Verify email**: Test registration with email verification
4. **Monitor metrics**: Check Railway dashboard for performance
5. **Set up alerts**: Configure notifications for deployment failures

## Success Metrics

Deployment is successful when:
- Health check returns 200 OK
- All API endpoints responding
- Database connected
- Email verification working
- No errors in logs
- Response times < 500ms
- Memory usage stable

---

Last updated: 2025-10-10
Deployment URL: https://api.yetai.app
Repository: https://github.com/benyetra/YetAI
