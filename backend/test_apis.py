#!/usr/bin/env python3
"""Test external API connections"""

import requests
import json
from datetime import datetime

# Test The Odds API (you'll need to add your key)
def test_odds_api():
    api_key = "YOUR_API_KEY"  # Add your actual key here
    url = f"https://api.the-odds-api.com/v4/sports?api_key={api_key}"
    
    try:
        response = requests.get(url)
        if response.status_code == 200:
            sports = response.json()
            print(f"✅ Odds API: {len(sports)} sports available")
            return True
        else:
            print(f"❌ Odds API error: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Odds API error: {e}")
        return False

# Test ESPN NFL API (free)
def test_espn_api():
    url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
    
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            games = len(data.get('events', []))
            print(f"✅ ESPN API: {games} NFL games found")
            return True
        else:
            print(f"❌ ESPN API error: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ ESPN API error: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Testing External APIs...")
    print("-" * 30)
    
    odds_ok = test_odds_api()
    espn_ok = test_espn_api()
    
    if odds_ok and espn_ok:
        print("\n🎉 All APIs working! Ready to build features.")
    else:
        print("\n⚠️  Some APIs need setup. Check API keys and try again.")

