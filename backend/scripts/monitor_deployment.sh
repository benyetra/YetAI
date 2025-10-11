#!/bin/bash
# Real-time Deployment Monitoring Script for YetAI Backend
# Monitors Railway deployment and health status

API_URL="${1:-https://api.yetai.app}"
CHECK_INTERVAL=5
MAX_CHECKS=60  # 5 minutes total

echo "================================================"
echo "YetAI Backend Deployment Monitor"
echo "================================================"
echo "API URL: $API_URL"
echo "Started: $(date)"
echo "================================================"
echo ""

check_count=0
consecutive_failures=0
max_consecutive_failures=3

while [ $check_count -lt $MAX_CHECKS ]; do
    check_count=$((check_count + 1))
    timestamp=$(date "+%Y-%m-%d %H:%M:%S")

    # Health check
    health_status=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/health" 2>/dev/null)

    if [ "$health_status" = "200" ]; then
        # Get full health response
        health_response=$(curl -s "$API_URL/health" 2>/dev/null)

        echo "[$timestamp] ✅ HEALTHY (HTTP $health_status)"
        echo "  Response: $health_response"

        # Test other endpoints periodically (every 6 checks = 30 seconds)
        if [ $((check_count % 6)) -eq 0 ]; then
            echo ""
            echo "  Running extended checks..."

            # API Status
            status_code=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/api/status" 2>/dev/null)
            if [ "$status_code" = "200" ]; then
                echo "  ✅ API Status: OK ($status_code)"
            else
                echo "  ❌ API Status: FAILED ($status_code)"
            fi

            # Database
            db_code=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/test-db" 2>/dev/null)
            if [ "$db_code" = "200" ]; then
                echo "  ✅ Database: Connected ($db_code)"
            else
                echo "  ❌ Database: FAILED ($db_code)"
            fi

            # Chat Suggestions
            chat_code=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/api/chat/suggestions" 2>/dev/null)
            if [ "$chat_code" = "200" ]; then
                echo "  ✅ Chat API: OK ($chat_code)"
            else
                echo "  ❌ Chat API: FAILED ($chat_code)"
            fi

            echo ""
        fi

        consecutive_failures=0
    else
        consecutive_failures=$((consecutive_failures + 1))
        echo "[$timestamp] ❌ UNHEALTHY (HTTP $health_status) - Failure $consecutive_failures/$max_consecutive_failures"

        if [ $consecutive_failures -ge $max_consecutive_failures ]; then
            echo ""
            echo "================================================"
            echo "⚠️  WARNING: $max_consecutive_failures consecutive failures detected!"
            echo "================================================"
            echo "Check Railway logs: railway logs"
            echo "Check GitHub Actions: gh run list"
            echo "================================================"
        fi
    fi

    # Sleep before next check (unless it's the last check)
    if [ $check_count -lt $MAX_CHECKS ]; then
        sleep $CHECK_INTERVAL
    fi
done

echo ""
echo "================================================"
echo "Monitoring Complete"
echo "Total Checks: $check_count"
echo "Ended: $(date)"
echo "================================================"
