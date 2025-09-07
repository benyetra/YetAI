# YetAI Sports Betting MVP - Deployment Guide

## 🚀 Production Infrastructure

**Domain**: yetai.app  
**Total Cost**: ~$5-10/month

### Architecture
- **Frontend**: Vercel (Free) - `yetai.app`
- **Backend API**: Railway ($5-10/month) - `api.yetai.app`  
- **Database**: Railway PostgreSQL (included)
- **Cache**: Railway Redis (optional, $5/month)

## 📋 Deployment Checklist

### 1. Railway Backend Deployment

1. **Create Railway Account**: https://railway.app
2. **Create New Project**: "YetAI Backend"
3. **Add PostgreSQL Database**: 
   - Click "Add Service" → "Database" → "PostgreSQL"
   - Note the connection string

4. **Deploy Backend**:
   ```bash
   # Install Railway CLI
   npm install -g @railway/cli
   
   # Login to Railway
   railway login
   
   # Navigate to backend directory
   cd backend/
   
   # Initialize Railway project
   railway link [your-project-id]
   
   # Deploy
   railway up
   ```

5. **Configure Environment Variables** in Railway Dashboard:
   ```
   DATABASE_URL=postgresql://postgres:[password]@[host]:[port]/[database]
   SECRET_KEY=[generate-secure-key]
   JWT_SECRET_KEY=[generate-secure-jwt-key]
   ODDS_API_KEY=[your-odds-api-key]
   ENVIRONMENT=production
   DEBUG=False
   ALLOWED_ORIGINS=https://yetai.app,https://www.yetai.app
   ```

6. **Custom Domain**: 
   - In Railway project settings → "Domains"
   - Add custom domain: `api.yetai.app`

### 2. Vercel Frontend Deployment

1. **Create Vercel Account**: https://vercel.com
2. **Connect GitHub Repository**:
   - Import project from GitHub
   - Select the frontend directory
   
3. **Configure Build Settings**:
   - Framework: Next.js
   - Build Command: `npm run build`
   - Output Directory: `.next`
   - Install Command: `npm install`

4. **Environment Variables** in Vercel:
   ```
   NEXT_PUBLIC_API_URL=https://api.yetai.app
   NEXT_PUBLIC_APP_URL=https://yetai.app
   NODE_ENV=production
   ```

5. **Custom Domain**:
   - In Vercel project settings → "Domains" 
   - Add: `yetai.app` and `www.yetai.app`

### 3. DNS Configuration

Configure these DNS records for `yetai.app`:

```
# Frontend (Vercel)
Type: CNAME
Name: @
Value: cname.vercel-dns.com

Type: CNAME  
Name: www
Value: cname.vercel-dns.com

# Backend API (Railway)
Type: CNAME
Name: api
Value: [railway-domain]
```

## 🔧 Post-Deployment Setup

### Database Migration
```bash
# Run on Railway after deployment
railway run alembic upgrade head
```

### Health Checks
- Backend: `https://api.yetai.app/health`
- Frontend: `https://yetai.app`

### SSL Certificates
- Vercel: Automatic SSL
- Railway: Automatic SSL

## 📈 Monitoring & Maintenance

### Railway Dashboard
- View logs and metrics
- Scale up/down as needed
- Monitor database usage

### Vercel Dashboard  
- View deployment logs
- Monitor function usage
- Analytics and performance

### Recommended Monitoring
- Railway built-in monitoring
- Sentry for error tracking (optional)
- Uptime monitoring service

## 💰 Cost Breakdown

| Service | Plan | Cost |
|---------|------|------|
| Domain | yetai.app | $0 (owned) |
| Vercel | Hobby | $0/month |
| Railway | Pro | $5-10/month |
| **Total** | | **$5-10/month** |

## 🚨 Security Considerations

1. **Environment Variables**: Never commit production secrets
2. **CORS**: Properly configured for yetai.app only
3. **HTTPS**: Enforced on all endpoints
4. **Database**: Railway PostgreSQL with SSL
5. **JWT**: Secure token generation and expiration

## 🔄 CI/CD Pipeline

### Automatic Deployments
- **Frontend**: Auto-deploy on push to `main` branch
- **Backend**: Auto-deploy on push to `main` branch

### Manual Deployments
```bash
# Frontend (from frontend directory)
vercel --prod

# Backend (from backend directory)  
railway up
```

## 📚 Quick Commands

```bash
# View Railway logs
railway logs

# Check Railway status
railway status

# View Vercel deployments
vercel ls

# Check deployment status
curl -I https://api.yetai.app/health
curl -I https://yetai.app
```