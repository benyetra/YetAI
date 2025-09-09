#!/usr/bin/env python3
"""
Comprehensive endpoint test script to verify all 404 fixes
Tests all the endpoints that were missing and causing 404 errors
"""
import requests
import json
import sys
import os
from datetime import datetime
from typing import Dict, List

# Base URL for testing
BASE_URL = "http://localhost:8000"

class EndpointTester:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.auth_token = None
        self.test_results = []
        self.session = requests.Session()
        
    def log_result(self, endpoint: str, method: str, status_code: int, success: bool, message: str = ""):
        """Log test result"""
        result = {
            "endpoint": endpoint,
            "method": method,
            "status_code": status_code,
            "success": success,
            "message": message,
            "timestamp": datetime.now().isoformat()
        }
        self.test_results.append(result)
        
        status_icon = "✅" if success else "❌"
        print(f"{status_icon} {method} {endpoint} -> {status_code} {message}")
    
    def test_endpoint(self, method: str, endpoint: str, data: Dict = None, 
                     headers: Dict = None, expect_success: bool = True) -> bool:
        """Test a single endpoint"""
        url = f"{self.base_url}{endpoint}"
        
        # Default headers
        test_headers = {"Content-Type": "application/json"}
        if self.auth_token:
            test_headers["Authorization"] = f"Bearer {self.auth_token}"
        if headers:
            test_headers.update(headers)
            
        try:
            if method == "GET":
                response = self.session.get(url, headers=test_headers)
            elif method == "POST":
                response = self.session.post(url, json=data, headers=test_headers)
            elif method == "PUT":
                response = self.session.put(url, json=data, headers=test_headers)
            elif method == "DELETE":
                response = self.session.delete(url, headers=test_headers)
            elif method == "OPTIONS":
                response = self.session.options(url, headers=test_headers)
            else:
                self.log_result(endpoint, method, 0, False, f"Unknown method: {method}")
                return False
                
            # Check if endpoint exists (not 404)
            endpoint_exists = response.status_code != 404
            
            if not endpoint_exists:
                self.log_result(endpoint, method, response.status_code, False, "404 Not Found")
                return False
                
            # For authenticated endpoints, 401/403 is acceptable if no auth provided
            if response.status_code in [401, 403] and not self.auth_token:
                self.log_result(endpoint, method, response.status_code, True, "Auth required (expected)")
                return True
                
            # Success range (200-299) or expected failure codes
            success = response.status_code < 400 or response.status_code in [401, 403]
            
            try:
                response_data = response.json()
                message = response_data.get("message", "")
            except:
                message = response.text[:100] if response.text else ""
                
            self.log_result(endpoint, method, response.status_code, success, message)
            return success
            
        except requests.exceptions.ConnectionError:
            self.log_result(endpoint, method, 0, False, "Connection Error - Is server running?")
            return False
        except Exception as e:
            self.log_result(endpoint, method, 0, False, f"Exception: {str(e)}")
            return False
    
    def test_yetai_bets_endpoints(self):
        """Test YetAI Bets endpoints"""
        print("\n🧠 Testing YetAI Bets Endpoints...")
        
        self.test_endpoint("OPTIONS", "/api/yetai-bets")
        self.test_endpoint("GET", "/api/yetai-bets")
        
        # Admin endpoint (will require auth)
        self.test_endpoint("OPTIONS", "/api/admin/yetai-bets/test-id")
        self.test_endpoint("DELETE", "/api/admin/yetai-bets/test-id")
    
    def test_sports_betting_endpoints(self):
        """Test Sports Betting endpoints"""
        print("\n🎯 Testing Sports Betting Endpoints...")
        
        # Bet placement
        self.test_endpoint("OPTIONS", "/api/bets/place")
        self.test_endpoint("POST", "/api/bets/place", {
            "bet_type": "moneyline",
            "selection": "Kansas City Chiefs",
            "odds": -110,
            "amount": 100,
            "game_id": "test-game-1",
            "home_team": "Kansas City Chiefs",
            "away_team": "Buffalo Bills",
            "sport": "NFL"
        })
        
        # Parlay betting
        self.test_endpoint("OPTIONS", "/api/bets/parlay") 
        self.test_endpoint("POST", "/api/bets/parlay", {
            "amount": 50,
            "legs": [
                {
                    "bet_type": "moneyline",
                    "selection": "Chiefs ML",
                    "odds": -150,
                    "game_id": "game-1"
                },
                {
                    "bet_type": "spread", 
                    "selection": "Lakers -3.5",
                    "odds": -110,
                    "game_id": "game-2"
                }
            ]
        })
        
        # Parlay management
        self.test_endpoint("OPTIONS", "/api/bets/parlays")
        self.test_endpoint("GET", "/api/bets/parlays")
        self.test_endpoint("GET", "/api/bets/parlay/test-parlay-id")
        
        # Bet history and stats
        self.test_endpoint("OPTIONS", "/api/bets/history")
        self.test_endpoint("POST", "/api/bets/history", {
            "status": "pending",
            "limit": 10
        })
        
        self.test_endpoint("OPTIONS", "/api/bets/stats")
        self.test_endpoint("GET", "/api/bets/stats")
        
        # Bet sharing
        self.test_endpoint("OPTIONS", "/api/bets/share")
        self.test_endpoint("POST", "/api/bets/share", {
            "bet_id": "test-bet-id",
            "message": "Great bet!"
        })
        
        self.test_endpoint("OPTIONS", "/api/bets/shared")
        self.test_endpoint("GET", "/api/bets/shared")
        self.test_endpoint("DELETE", "/api/bets/shared/test-share-id")
        
        # Bet management
        self.test_endpoint("OPTIONS", "/api/bets/test-bet-id")
        self.test_endpoint("DELETE", "/api/bets/test-bet-id")
        
        # Simulation
        self.test_endpoint("OPTIONS", "/api/bets/simulate")
        self.test_endpoint("POST", "/api/bets/simulate")
    
    def test_fantasy_endpoints(self):
        """Test Fantasy Sports endpoints"""
        print("\n🏈 Testing Fantasy Sports Endpoints...")
        
        self.test_endpoint("OPTIONS", "/api/fantasy/accounts")
        self.test_endpoint("GET", "/api/fantasy/accounts")
        
        self.test_endpoint("OPTIONS", "/api/fantasy/leagues")
        self.test_endpoint("GET", "/api/fantasy/leagues")
        
        self.test_endpoint("OPTIONS", "/api/fantasy/connect")
        self.test_endpoint("POST", "/api/fantasy/connect", {
            "platform": "sleeper",
            "credentials": {"username": "test_user"}
        })
        
        self.test_endpoint("OPTIONS", "/api/fantasy/roster/test-league-id")
        self.test_endpoint("GET", "/api/fantasy/roster/test-league-id")
        
        self.test_endpoint("GET", "/api/fantasy/projections")
    
    def test_odds_markets_endpoints(self):
        """Test Odds and Markets endpoints"""
        print("\n📊 Testing Odds & Markets Endpoints...")
        
        # NFL
        self.test_endpoint("OPTIONS", "/api/odds/americanfootball_nfl")
        self.test_endpoint("GET", "/api/odds/americanfootball_nfl")
        
        # NBA
        self.test_endpoint("OPTIONS", "/api/odds/basketball_nba") 
        self.test_endpoint("GET", "/api/odds/basketball_nba")
        
        # MLB
        self.test_endpoint("OPTIONS", "/api/odds/baseball_mlb")
        self.test_endpoint("GET", "/api/odds/baseball_mlb")
        
        # NHL (Ice Hockey) - This was a major missing endpoint
        self.test_endpoint("OPTIONS", "/api/odds/icehockey_nhl")
        self.test_endpoint("GET", "/api/odds/icehockey_nhl")
        
        # Hockey alias
        self.test_endpoint("OPTIONS", "/api/odds/hockey")
        self.test_endpoint("GET", "/api/odds/hockey")
        
        # Popular sports
        self.test_endpoint("GET", "/api/odds/popular")
    
    def test_parlay_specific_endpoints(self):
        """Test Parlay-specific endpoints"""
        print("\n🎲 Testing Parlay-Specific Endpoints...")
        
        self.test_endpoint("OPTIONS", "/api/parlays/markets")
        self.test_endpoint("GET", "/api/parlays/markets")
        self.test_endpoint("GET", "/api/parlays/markets?sport=icehockey_nhl")
        
        self.test_endpoint("OPTIONS", "/api/parlays/popular")
        self.test_endpoint("GET", "/api/parlays/popular")
    
    def test_profile_status_endpoints(self):
        """Test Profile and Status endpoints"""
        print("\n👤 Testing Profile & Status Endpoints...")
        
        self.test_endpoint("OPTIONS", "/api/profile/sports")
        self.test_endpoint("GET", "/api/profile/sports")
        
        self.test_endpoint("OPTIONS", "/api/profile/status") 
        self.test_endpoint("GET", "/api/profile/status")
    
    def test_live_betting_endpoints(self):
        """Test existing Live Betting endpoints"""
        print("\n⚡ Testing Live Betting Endpoints...")
        
        self.test_endpoint("OPTIONS", "/api/live-bets/markets")
        self.test_endpoint("GET", "/api/live-bets/markets")
        
        self.test_endpoint("OPTIONS", "/api/live-bets/active")
        self.test_endpoint("GET", "/api/live-bets/active")
    
    def test_core_endpoints(self):
        """Test Core API endpoints"""
        print("\n🔧 Testing Core API Endpoints...")
        
        self.test_endpoint("GET", "/api/status")
        self.test_endpoint("GET", "/api/auth/status") 
        self.test_endpoint("GET", "/health")
        self.test_endpoint("GET", "/")
        
        # New health check endpoint
        self.test_endpoint("GET", "/api/endpoints/health")
    
    def run_all_tests(self):
        """Run all endpoint tests"""
        print("🚀 Starting Comprehensive Endpoint Testing...")
        print(f"Testing against: {self.base_url}")
        print("=" * 60)
        
        # Test core endpoints first
        self.test_core_endpoints()
        
        # Test all major endpoint categories
        self.test_yetai_bets_endpoints()
        self.test_sports_betting_endpoints() 
        self.test_fantasy_endpoints()
        self.test_odds_markets_endpoints()
        self.test_parlay_specific_endpoints()
        self.test_profile_status_endpoints()
        self.test_live_betting_endpoints()
        
        self.print_summary()
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "=" * 60)
        print("📋 TEST SUMMARY")
        print("=" * 60)
        
        total_tests = len(self.test_results)
        successful_tests = len([r for r in self.test_results if r["success"]])
        failed_tests = total_tests - successful_tests
        
        print(f"Total Endpoints Tested: {total_tests}")
        print(f"✅ Successful: {successful_tests}")
        print(f"❌ Failed: {failed_tests}")
        print(f"Success Rate: {(successful_tests/total_tests)*100:.1f}%")
        
        if failed_tests > 0:
            print(f"\n❌ FAILED TESTS ({failed_tests}):")
            print("-" * 40)
            for result in self.test_results:
                if not result["success"]:
                    print(f"  {result['method']} {result['endpoint']} -> {result['status_code']} {result['message']}")
        
        # Categorize by endpoint type
        endpoint_categories = {}
        for result in self.test_results:
            category = self._categorize_endpoint(result["endpoint"])
            if category not in endpoint_categories:
                endpoint_categories[category] = {"total": 0, "success": 0}
            endpoint_categories[category]["total"] += 1
            if result["success"]:
                endpoint_categories[category]["success"] += 1
        
        print(f"\n📊 SUCCESS BY CATEGORY:")
        print("-" * 40)
        for category, stats in endpoint_categories.items():
            success_rate = (stats["success"] / stats["total"]) * 100
            print(f"  {category}: {stats['success']}/{stats['total']} ({success_rate:.1f}%)")
        
        print(f"\n⏱️  Test completed at: {datetime.now().isoformat()}")
        
        # Save detailed results
        self.save_results()
    
    def _categorize_endpoint(self, endpoint: str) -> str:
        """Categorize endpoint by type"""
        if "/yetai-bets" in endpoint or "/admin/yetai-bets" in endpoint:
            return "YetAI Bets"
        elif "/bets/" in endpoint:
            return "Sports Betting" 
        elif "/fantasy/" in endpoint:
            return "Fantasy Sports"
        elif "/odds/" in endpoint:
            return "Odds & Markets"
        elif "/parlays/" in endpoint:
            return "Parlays"
        elif "/profile/" in endpoint:
            return "Profile & Status"
        elif "/live-bets/" in endpoint:
            return "Live Betting"
        elif "/auth/" in endpoint:
            return "Authentication"
        else:
            return "Core API"
    
    def save_results(self):
        """Save test results to file"""
        filename = f"endpoint_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(os.path.dirname(__file__), filename)
        
        with open(filepath, 'w') as f:
            json.dump({
                "test_run": {
                    "timestamp": datetime.now().isoformat(),
                    "base_url": self.base_url,
                    "total_tests": len(self.test_results),
                    "successful_tests": len([r for r in self.test_results if r["success"]]),
                    "failed_tests": len([r for r in self.test_results if not r["success"]])
                },
                "results": self.test_results
            }, f, indent=2)
        
        print(f"\n💾 Detailed results saved to: {filename}")

def main():
    """Main test runner"""
    # Check if custom base URL provided
    base_url = sys.argv[1] if len(sys.argv) > 1 else BASE_URL
    
    tester = EndpointTester(base_url)
    
    try:
        tester.run_all_tests()
        
        # Return appropriate exit code
        failed_tests = len([r for r in tester.test_results if not r["success"]])
        if failed_tests > 0:
            print(f"\n⚠️  {failed_tests} tests failed. Check the summary above.")
            sys.exit(1)
        else:
            print(f"\n🎉 All tests passed! No 404 errors found.")
            sys.exit(0)
            
    except KeyboardInterrupt:
        print(f"\n\n⏹️  Testing interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n💥 Testing failed with exception: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()