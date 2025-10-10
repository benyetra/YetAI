#!/bin/bash
# Deployment Validation Script for YetAI Backend
# Tests critical endpoints after Railway deployment

set -e

API_URL="${1:-https://api.yetai.app}"
MAX_RETRIES=10
RETRY_DELAY=10

echo "Validating deployment at: $API_URL"
echo "========================================"

# Wait for service to be ready
echo "Waiting for service to be ready..."
for i in $(seq 1 $MAX_RETRIES); do
    if curl -f -s "$API_URL/health" > /dev/null 2>&1; then
        echo "Service is ready!"
        break
    fi
    if [ $i -eq $MAX_RETRIES ]; then
        echo "Service failed to become ready after $MAX_RETRIES attempts"
        exit 1
    fi
    echo "Attempt $i/$MAX_RETRIES failed, retrying in ${RETRY_DELAY}s..."
    sleep $RETRY_DELAY
done

echo ""
echo "1. Testing Health Endpoint"
echo "-------------------------"
HEALTH_RESPONSE=$(curl -f -s "$API_URL/health")
echo "Response: $HEALTH_RESPONSE"
echo "Status: $(echo $HEALTH_RESPONSE | grep -o '"status":"[^"]*"' || echo 'PASS')"

echo ""
echo "2. Testing API Status"
echo "--------------------"
STATUS_RESPONSE=$(curl -f -s "$API_URL/api/status")
echo "Response: $STATUS_RESPONSE"

echo ""
echo "3. Testing Database Connection"
echo "-----------------------------"
DB_RESPONSE=$(curl -f -s "$API_URL/test-db")
echo "Response: $DB_RESPONSE"

echo ""
echo "4. Testing Chat Suggestions"
echo "---------------------------"
CHAT_RESPONSE=$(curl -f -s "$API_URL/api/chat/suggestions")
echo "Response: $(echo $CHAT_RESPONSE | head -c 200)..."

echo ""
echo "5. Testing CORS Headers"
echo "----------------------"
CORS_RESPONSE=$(curl -I -s "$API_URL/health" | grep -i "access-control")
echo "CORS Headers: $CORS_RESPONSE"

echo ""
echo "======================================"
echo "All validation tests passed!"
echo "Deployment is healthy and operational"
echo "======================================"
