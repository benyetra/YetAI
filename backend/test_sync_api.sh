#!/bin/bash

echo "============================================"
echo "Testing Game Sync API Endpoint"
echo "============================================"
echo ""

# First, let's check if the server is running
echo "Checking if backend is running..."
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✅ Backend is running"
else
    echo "❌ Backend is not running!"
    echo "Please start the backend first:"
    echo "  cd backend && .venv/bin/uvicorn app.main:app --reload"
    exit 1
fi

echo ""
echo "Triggering game sync..."
echo ""

# Call the sync endpoint (you'll need to be logged in as admin)
# This is just a test - you'll need to call this from your admin panel with proper auth
curl -X POST http://localhost:8000/api/admin/games/sync-upcoming \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN_HERE" \
  | python3 -m json.tool

echo ""
echo "============================================"
echo "Note: You need to call this from your admin"
echo "panel with proper authentication!"
echo "============================================"
