# CI/CD Pipeline Setup Guide

## Overview

This document provides step-by-step instructions to set up the complete CI/CD pipeline for the YetAI Sports Betting MVP, including both frontend and backend automated deployments.

## 📋 Prerequisites

- GitHub repository with admin access
- Railway account with project deployed
- Vercel account with project deployed
- OpenAI API key for testing

## 🔐 Required GitHub Secrets

### Backend Secrets

Set these in your GitHub repository under Settings → Secrets and variables → Actions:

| Secret Name | Description | Where to Get It |
|-------------|-------------|-----------------|
| `RAILWAY_TOKEN` | Railway API token for production deployments | Railway → Account Settings → Tokens |
| `RAILWAY_STAGING_TOKEN` | Railway API token for staging deployments | Railway → Account Settings → Tokens |
| `OPENAI_API_KEY` | OpenAI API key for testing | OpenAI → API Keys |

### Frontend Secrets

| Secret Name | Description | Where to Get It |
|-------------|-------------|-----------------|
| `VERCEL_TOKEN` | Vercel API token | Vercel → Account Settings → Tokens |
| `VERCEL_ORG_ID` | Vercel organization ID | Run `vercel whoami` |
| `VERCEL_PROJECT_ID` | Vercel project ID | Vercel project settings |
| `LHCI_GITHUB_APP_TOKEN` | Lighthouse CI GitHub app token | Optional for Lighthouse CI |
| `LHCI_TOKEN` | Lighthouse CI token | Optional for Lighthouse CI |

## 🚀 Setup Instructions

### Step 1: Get Railway Tokens

1. Go to [Railway Dashboard](https://railway.app/dashboard)
2. Click on your profile → Account Settings
3. Navigate to "Tokens" section
4. Create a new token with appropriate permissions
5. Copy the token and add it to GitHub secrets

```bash
# Test your Railway token
railway login --token YOUR_TOKEN_HERE
railway status
```

### Step 2: Get Vercel Tokens

1. Go to [Vercel Dashboard](https://vercel.com/dashboard)
2. Click on your profile → Account Settings
3. Navigate to "Tokens" section
4. Create a new token
5. Get your Org ID and Project ID:

```bash
# Install Vercel CLI
npm i -g vercel

# Login and get IDs
vercel login
vercel whoami  # This shows your ORG_ID

# In your project directory
vercel link
# This will show your PROJECT_ID
```

### Step 3: Add Secrets to GitHub

1. Go to your GitHub repository
2. Navigate to Settings → Secrets and variables → Actions
3. Click "New repository secret"
4. Add each secret from the tables above

### Step 4: Configure Branch Protection (Optional but Recommended)

1. Go to Settings → Branches
2. Add rule for `main` branch:
   - Require status checks to pass before merging
   - Require branches to be up to date before merging
   - Require deployments to succeed before merging

## 🔄 Pipeline Workflow

### Backend Pipeline (`backend-ci-cd.yml`)

**Triggers:**
- Push to `main` or `develop` branches (when backend files change)
- Pull requests to `main` branch

**Jobs:**
1. **Test**: Runs unit tests, linting, and type checking
2. **Security Scan**: Runs Bandit security scan and vulnerability checks
3. **Deploy Staging**: Deploys to staging environment (`develop` branch)
4. **Deploy Production**: Deploys to production environment (`main` branch)

**Features:**
- PostgreSQL service for testing
- Code coverage reporting
- Security vulnerability scanning
- Automated health checks post-deployment
- API endpoint validation

### Frontend Pipeline (`frontend-ci-cd.yml`)

**Triggers:**
- Push to `main` or `develop` branches (when frontend files change)
- Pull requests to `main` branch

**Jobs:**
1. **Test**: Runs Jest tests, linting, and type checking
2. **Accessibility Test**: Runs axe-core accessibility tests
3. **Security Scan**: Runs npm audit and dependency scanning
4. **Deploy Preview**: Creates preview deployments for PRs
5. **Deploy Staging**: Deploys to staging environment (`develop` branch)
6. **Deploy Production**: Deploys to production environment (`main` branch)
7. **Lighthouse Audit**: Runs performance and quality audits

## 📊 Test Configuration

### Backend Testing

**Located in:** `backend/tests/`
- Unit tests with pytest
- Integration tests with TestClient
- Database tests with PostgreSQL service
- Security tests with Bandit
- Code coverage with pytest-cov

**Run tests locally:**
```bash
cd backend
pip install pytest pytest-asyncio pytest-cov httpx
pytest --cov=app --cov-report=html -v
```

### Frontend Testing

**Located in:** `frontend/__tests__/` and `frontend/**/*.test.(js|ts|jsx|tsx)`
- Unit tests with Jest and React Testing Library
- Component tests
- Accessibility tests with axe-core
- Security audits with audit-ci

**Run tests locally:**
```bash
cd frontend
npm install
npm run test
npm run test:coverage
```

## 🔧 Local Development Workflow

### Backend Development

1. Create feature branch: `git checkout -b feature/your-feature`
2. Make changes in `backend/` directory
3. Run tests: `pytest`
4. Run linting: `black . && flake8 .`
5. Commit and push
6. Create pull request

### Frontend Development

1. Create feature branch: `git checkout -b feature/your-feature`
2. Make changes in `frontend/` directory
3. Run tests: `npm test`
4. Run linting: `npm run lint`
5. Commit and push
6. Create pull request

## 🚨 Troubleshooting

### Common Issues

**Railway Deployment Fails:**
- Check Railway token has correct permissions
- Verify `railway.json` configuration
- Check Railway service logs

**Vercel Deployment Fails:**
- Verify Vercel token and project IDs
- Check build logs in Vercel dashboard
- Ensure environment variables are set

**Tests Failing:**
- Check if all dependencies are installed
- Verify test database setup
- Check environment variables in CI

### Debug Commands

```bash
# Test Railway connection
railway login --token $RAILWAY_TOKEN
railway status

# Test Vercel connection
vercel whoami --token $VERCEL_TOKEN

# Run tests with verbose output
pytest -v -s
npm test -- --verbose
```

## 📈 Monitoring and Notifications

### Pipeline Status

- GitHub Actions tab shows all workflow runs
- Failed deployments trigger notification jobs
- Successful deployments run health checks

### Production Monitoring

**Backend:** 
- Health check: `https://backend-production-f7af.up.railway.app/health`
- API status: `https://backend-production-f7af.up.railway.app/api/status`

**Frontend:**
- Site: `https://yetai.app`
- Vercel dashboard for deployment status

## 🎯 Best Practices

1. **Always test locally before pushing**
2. **Use feature branches for new development**
3. **Keep secrets secure and rotate regularly**
4. **Monitor pipeline performance and optimize as needed**
5. **Review failed deployments immediately**
6. **Keep dependencies updated**
7. **Run security scans regularly**

## 📚 Additional Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Railway Documentation](https://docs.railway.app/)
- [Vercel Documentation](https://vercel.com/docs)
- [Jest Testing Framework](https://jestjs.io/)
- [PyTest Documentation](https://docs.pytest.org/)

---

🚀 **Your CI/CD pipeline is now ready for automated deployments!**