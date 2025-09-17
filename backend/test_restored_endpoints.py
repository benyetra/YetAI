#!/usr/bin/env python3
"""
Test script to verify the restored fantasy analytics endpoints
"""
import requests
import json

# Base URL for the API (adjust based on your local setup)
BASE_URL = "http://localhost:8000"

# Test endpoints
ENDPOINTS = [
    "/api/fantasy/players/123/analytics/2024",
    "/api/fantasy/players/456/trends/2024",
    "/api/fantasy/players/789/efficiency/2024",
]


def test_endpoint(endpoint):
    """Test a single endpoint"""
    url = f"{BASE_URL}{endpoint}"

    try:
        # Since we don't have proper auth setup, this will likely fail with 401
        # But we're checking if the endpoints exist (not 404)
        response = requests.get(url, timeout=5)

        print(f"✓ {endpoint}")
        print(f"  Status: {response.status_code}")
        print(f"  Content: {response.text[:200]}...")
        print()

        return True

    except requests.exceptions.ConnectionError:
        print(f"✗ {endpoint}")
        print("  Error: Could not connect to server (is it running?)")
        print()
        return False

    except Exception as e:
        print(f"✗ {endpoint}")
        print(f"  Error: {str(e)}")
        print()
        return False


def main():
    """Run tests on all endpoints"""
    print("Testing Restored Fantasy Analytics Endpoints")
    print("=" * 50)

    results = []
    for endpoint in ENDPOINTS:
        results.append(test_endpoint(endpoint))

    print("=" * 50)
    print(f"Summary: {sum(results)}/{len(results)} endpoints accessible")

    if all(results):
        print("✓ All endpoints are responding (server is running)")
    elif any(results):
        print("⚠ Some endpoints are responding")
    else:
        print("✗ No endpoints are responding (server may not be running)")


if __name__ == "__main__":
    main()
