# User Management Guide

This guide explains how to create and manage test users for the YetAI Sports Betting MVP platform.

## Available User Management Tools

### 1. Shell Script (Recommended)
- **File**: `create_test_users.sh`
- **Requirements**: curl (pre-installed on most systems)
- **Usage**: Simple bash commands

### 2. Python Script
- **File**: `create_test_users.py`
- **Requirements**: Python 3 + requests library
- **Usage**: More advanced programmatic access

## Quick Start

### Create Demo Users
```bash
./create_test_users.sh demo
```
This creates two demo accounts:
- 📧 `demo@example.com` | 🔑 `demo123` | 🏷️ free tier
- 📧 `pro@example.com` | 🔑 `pro123` | 🏷️ pro tier

### Create Individual User
```bash
./create_test_users.sh create john@test.com password123 John Doe
```

### Create Batch Test Users
```bash
./create_test_users.sh batch
```
This creates 8 test users:
- alice@test.com, bob@test.com, charlie@test.com, etc.
- All with password: `test123`

### Test Login
```bash
./create_test_users.sh login demo@example.com demo123
```

## Available Commands

| Command | Description | Example |
|---------|-------------|---------|
| `demo` | Create demo users | `./create_test_users.sh demo` |
| `create` | Create single user | `./create_test_users.sh create email@test.com pass123 First Last` |
| `login` | Test login | `./create_test_users.sh login email@test.com pass123` |
| `batch` | Create 8 test users | `./create_test_users.sh batch` |
| `test-all` | Run complete test suite | `./create_test_users.sh test-all` |
| `help` | Show help menu | `./create_test_users.sh help` |

## User Account Tiers

### Free Tier (Default)
- Access to basic features
- Limited predictions
- Basic dashboard

### Pro Tier
- Advanced AI insights
- Profit/Loss tracking
- Premium features
- Unlimited predictions

### Elite Tier
- All pro features
- Priority support
- Exclusive content

## Frontend Authentication

### Login Interface
1. Navigate to `http://localhost:3001/`
2. Click "Sign In" button
3. Switch to "Sign Up" tab for new accounts
4. Or use "Start Free Trial" button

### Current Session
- The browser currently shows user "Demo" (free tier) is logged in
- WebSocket connections are active
- Real-time betting odds are updating
- All UI formatting is working correctly

## Authentication API Endpoints

### Backend Endpoints
- `POST /api/auth/signup` - Create new user
- `POST /api/auth/login` - User login
- `GET /api/auth/me` - Get current user info
- `POST /api/auth/upgrade` - Upgrade subscription
- `POST /api/auth/demo-users` - Create demo users

### Response Format
```json
{
  "status": "success",
  "message": "Account created successfully",
  "user": {
    "id": 1,
    "email": "user@test.com",
    "first_name": "John",
    "last_name": "Doe",
    "subscription_tier": "free",
    "is_verified": false
  },
  "access_token": "eyJ0eXAiOiJKV1Q...",
  "token_type": "bearer"
}
```

## Development Notes

### In-Memory Storage
- Users are stored in memory (not persistent database)
- Restart backend to clear all users
- Demo users are auto-created on startup

### Password Security
- Passwords are hashed using bcrypt
- JWT tokens for authentication
- Secure session management

### WebSocket Integration
- Real-time connections per user
- Live betting odds updates
- Game subscription system

## Troubleshooting

### Backend Not Running
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend Not Running
```bash
cd frontend
npm run dev
```

### Script Permissions
```bash
chmod +x create_test_users.sh
```

### API Connection Issues
- Verify backend is running on port 8000
- Check CORS settings in main.py
- Ensure API endpoints are accessible

## Current Status ✅

- ✅ User registration working
- ✅ User login working  
- ✅ JWT authentication working
- ✅ Demo users available
- ✅ Batch user creation working
- ✅ Frontend authentication UI working
- ✅ WebSocket connections working
- ✅ All betting odds formatting working
- ✅ Real-time updates working

## Test Users Available

### Demo Users (Always Available)
- demo@example.com / demo123 (free)
- pro@example.com / pro123 (pro)

### Batch Test Users (Created via script)
- alice@test.com / test123
- bob@test.com / test123
- charlie@test.com / test123
- diana@test.com / test123
- emma@test.com / test123
- frank@test.com / test123
- grace@test.com / test123
- henry@test.com / test123

---

*Last Updated: August 15, 2025*  
*All user management systems are operational and ready for testing.*