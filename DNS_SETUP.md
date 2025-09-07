# YetAI.app DNS Configuration Guide

## Domain Setup Instructions

Configure the following DNS records in your domain provider's dashboard (GoDaddy, Namecheap, etc.) for **yetai.app**:

### Frontend (Vercel)
Add these **A records** for the main website:

```
Type: A
Name: @        (or leave blank for root domain)
Value: 76.76.21.21

Type: A  
Name: www
Value: 76.76.21.21
```

### Backend API (Railway)
Add this **CNAME record** for the API:

```
Type: CNAME
Name: api
Value: 7nxfxg95.up.railway.app
```

## Final URLs After DNS Setup

- **Frontend**: https://yetai.app and https://www.yetai.app
- **Backend API**: https://api.yetai.app

## DNS Propagation
- Changes can take up to 72 hours to propagate worldwide
- Use tools like https://dnschecker.org to monitor propagation
- Vercel and Railway will automatically issue SSL certificates once DNS is configured

## Verification
Once DNS is configured, verify:

1. **Frontend**: Visit https://yetai.app
2. **Backend**: Visit https://api.yetai.app/health (once backend is working)

## Notes
- SSL certificates will be automatically provisioned by Vercel and Railway
- No additional configuration needed once DNS records are set
- Both platforms will handle HTTPS redirects automatically