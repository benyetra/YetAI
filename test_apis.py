#!/usr/bin/env python3
"""Test script for AI Sports Betting MVP APIs"""

import asyncio
import httpx
import sys
import json
from datetime import datetime

async def test_api_endpoint(client: httpx.AsyncClient, endpoint: str, expected_status: int = 200):
    """Test a single API endpoint"""
    try:
        print(f"  Testing {endpoint}...")
        response = await client.get(endpoint)
        
        if response.status_code == expected_status:
            print(f"    ✅ Status: {response.status_code}")
            try:
                data = response.json()
                print(f"    📄 Response: {json.dumps(data, indent=2)}")
                return True, data
            except json.JSONDecodeError:
                print(f"    📄 Response (text): {response.text}")
                return True, response.text
        else:
            print(f"    ❌ Expected {expected_status}, got {response.status_code}")
            print(f"    📄 Response: {response.text}")
            return False, None
            
    except Exception as e:
        print(f"    ❌ Error: {str(e)}")
        return False, None

async def test_backend_apis():
    """Test all backend API endpoints"""
    print("🧪 Testing AI Sports Betting MVP Backend APIs")
    print("=" * 50)
    
    base_url = "http://localhost:8000"
    
    # Test endpoints
    endpoints = [
        "/",
        "/health", 
        "/test/odds",
        "/test/fantasy",
        "/docs"  # This should return HTML
    ]
    
    total_tests = len(endpoints)
    passed_tests = 0
    
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
            
            print(f"🌐 Testing backend at: {base_url}")
            print(f"🕐 Timestamp: {datetime.now().isoformat()}")
            print()
            
            for endpoint in endpoints:
                success, data = await test_api_endpoint(client, endpoint)
                if success:
                    passed_tests += 1
                print()
            
            # Summary
            print("📊 Test Summary")
            print("-" * 30)
            print(f"Total tests: {total_tests}")
            print(f"Passed: {passed_tests}")
            print(f"Failed: {total_tests - passed_tests}")
            print(f"Success rate: {(passed_tests/total_tests)*100:.1f}%")
            
            if passed_tests == total_tests:
                print("\n🎉 All API tests passed!")
                return True
            else:
                print(f"\n❌ {total_tests - passed_tests} test(s) failed")
                return False
                
    except Exception as e:
        print(f"❌ Failed to connect to backend: {e}")
        print("\n💡 Make sure the backend is running:")
        print("   cd backend && source venv/bin/activate && uvicorn app.main:app --reload")
        return False

async def main():
    """Main test function"""
    print("🚀 AI Sports Betting MVP - API Test Suite")
    print("=" * 60)
    print()
    
    # Test backend
    backend_success = await test_backend_apis()
    
    print()
    print("🏁 Overall Results")
    print("-" * 20)
    
    if backend_success:
        print("✅ Backend APIs: All tests passed")
        print("\n🎯 Next steps:")
        print("  1. Visit http://localhost:3000 to test the frontend")
        print("  2. Use the API at http://localhost:8000/docs")
        print("  3. Start building your AI sports betting features!")
        sys.exit(0)
    else:
        print("❌ Backend APIs: Some tests failed")
        print("\n🔧 Troubleshooting:")
        print("  1. Make sure the backend is running")
        print("  2. Check if port 8000 is available")
        print("  3. Review the error messages above")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())