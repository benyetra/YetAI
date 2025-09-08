# Environment URL Refactoring Documentation

This document outlines the comprehensive refactoring performed to eliminate hardcoded URLs and implement proper environment switching across the YetAI Sports Betting MVP codebase.

## Summary of Changes

### 1. Frontend Centralized API Configuration

**Created:** `/frontend/src/lib/api-config.ts`

This new utility provides centralized API URL management with environment detection:

- **Environment Detection:** Automatically determines environment (development/staging/production) based on `window.location.hostname`
- **Environment Variable Priority:** Always checks `NEXT_PUBLIC_API_URL` first
- **Fallback URLs:** Provides appropriate defaults for each environment:
  - **Development:** `http://localhost:8000`
  - **Staging:** `https://staging-backend.up.railway.app`
  - **Production:** `https://backend-production-f7af.up.railway.app`

**Key Functions:**
- `getApiUrl(endpoint)` - Returns full API URL for any endpoint
- `getWsUrl(endpoint)` - Returns WebSocket URL for any endpoint
- `apiRequest(endpoint, options)` - Utility function with automatic auth token handling

### 2. Frontend Component Updates

**Files Updated:**
- `Auth.tsx` - Updated API client to use centralized config
- `BettingDashboard.tsx` - Replaced hardcoded URLs with `apiRequest`
- `PerformanceDashboard.tsx` - Updated to use centralized config
- `TradeAnalyzer.tsx` - All 5 hardcoded localhost URLs replaced
- `BetHistory.tsx` - Updated parlay detail fetching
- `ParlayList.tsx` - Updated parlay listing API calls
- `ParlayBuilder.tsx` - Updated parlay creation
- `YetAIBetModal.tsx` - Updated bet placement
- `Dashboard.tsx` - Fixed double fallback pattern
- `NotificationProvider.tsx` - Updated WebSocket URL generation
- `useWebSocket.ts` - Updated WebSocket connection logic

**Frontend App Pages Updated:**
- `app/admin/page.tsx` - All 4 hardcoded URLs replaced
- `app/predictions/page.tsx` - Both hardcoded URLs replaced
- `app/parlays/page.tsx` - Updated parlay fetching
- `app/login/page.tsx` - Removed railway.app hardcoded URLs

### 3. Backend Configuration Enhancement

**Enhanced:** `backend/app/core/config.py`

Added environment-aware configuration methods:

- `get_frontend_urls()` - Returns appropriate CORS origins based on environment
- `get_google_redirect_uri()` - Returns correct OAuth redirect URI
- Support for `FRONTEND_URL` and `ALLOWED_ORIGINS` environment variables

**Environment-Specific Defaults:**
- **Production:** `yetai.app`, `www.yetai.app`
- **Staging:** `staging.yetai.app`
- **Development:** Multiple localhost ports (3000-3003)

### 4. Backend Service Updates

**Files Updated:**
- `main.py` - Simplified CORS configuration to use centralized settings
- `google_oauth_service.py` - Uses environment-aware redirect URI
- `email_service.py` - Uses environment-aware frontend URL for email links
- `avatar_service.py` - Uses environment-aware backend URL for avatar paths

### 5. Environment Configuration Files

**Updated:**
- `backend/.env` - Added CORS configuration examples
- `backend/.env.example` - Added documentation for new environment variables
- `backend/.env.production` - Added production-specific CORS and OAuth settings

## Environment Variables

### Frontend (Next.js)
- `NEXT_PUBLIC_API_URL` - Primary API URL (overrides all defaults)

### Backend (FastAPI)
- `ENVIRONMENT` - Set to "development", "staging", or "production"
- `FRONTEND_URL` - Primary frontend URL for email links and redirects
- `ALLOWED_ORIGINS` - Comma-separated list of allowed CORS origins
- `GOOGLE_REDIRECT_URI` - OAuth redirect URI (optional, auto-determined if not set)

## Benefits of Refactoring

### 1. **Environment Flexibility**
- Seamless switching between local, staging, and production environments
- No more manual URL changes when deploying
- Automatic environment detection on frontend

### 2. **Maintainability**
- Single source of truth for API URLs in frontend
- Centralized CORS configuration in backend
- No more scattered hardcoded URLs throughout the codebase

### 3. **Development Experience**
- Automatic localhost fallbacks for development
- Support for multiple development ports
- Easy testing across different environments

### 4. **Security**
- Environment-specific CORS policies
- No production URLs accidentally used in development
- Proper OAuth redirect URI handling

### 5. **Deployment Reliability**
- Zero-configuration deployment with environment variables
- Consistent URL handling across all components
- Reduced risk of deployment-related URL issues

## Usage Examples

### Frontend API Calls
```typescript
// Before
const response = await fetch('http://localhost:8000/api/users');

// After
import { getApiUrl, apiRequest } from '@/lib/api-config';
const response = await apiRequest('/api/users');
// or
const response = await fetch(getApiUrl('/api/users'));
```

### Frontend WebSocket Connections
```typescript
// Before
const wsUrl = `ws://localhost:8000/ws/${userId}`;

// After
import { getWsUrl } from '@/lib/api-config';
const wsUrl = getWsUrl(`/ws/${userId}`);
```

### Backend CORS Configuration
```python
# Before - hardcoded origins
allow_origins=["http://localhost:3000", "https://yetai.app"]

# After - environment-aware
allow_origins=settings.get_frontend_urls()
```

## Migration Guide

For developers working with this codebase:

1. **Never hardcode URLs** - Always use the centralized configuration
2. **Set environment variables** - Use `NEXT_PUBLIC_API_URL` and backend environment variables
3. **Use the utilities** - Import `getApiUrl`, `getWsUrl`, and `apiRequest` from `@/lib/api-config`
4. **Test all environments** - Verify functionality in development, staging, and production

## Testing Verification

After this refactoring:
- ✅ No hardcoded localhost:8000 URLs in frontend
- ✅ No hardcoded railway.app URLs in frontend  
- ✅ No hardcoded yetai.app URLs in backend
- ✅ All API calls use centralized configuration
- ✅ WebSocket connections use environment-aware URLs
- ✅ CORS origins are environment-specific
- ✅ OAuth redirects work in all environments

This refactoring ensures the application can seamlessly operate across development, staging, and production environments without manual URL changes.