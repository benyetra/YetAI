# data_audit.py - Test what data is real vs mock

import asyncio
import aiohttp
import requests
from datetime import datetime


class DataAudit:
    """Audit all data sources to identify real vs mock data"""

    def __init__(self):
        self.base_url = "http://localhost:8000"

    async def audit_all_endpoints(self):
        """Test all endpoints and identify data sources"""
        print("🔍 DATA SOURCE AUDIT")
        print("=" * 50)

        results = {}

        # 1. Test Games Data (Should be real ESPN data)
        print("\n📊 TESTING GAMES DATA")
        try:
            response = requests.get(f"{self.base_url}/api/games/nfl")
            if response.status_code == 200:
                games_data = response.json()
                games = games_data.get("games", [])

                if games:
                    sample_game = games[0]
                    print(f"✅ Games API Working: {len(games)} games found")
                    print(
                        f"   Sample: {sample_game.get('away_team_full')} @ {sample_game.get('home_team_full')}"
                    )
                    print(f"   Date: {sample_game.get('date')}")
                    print(f"   Venue: {sample_game.get('venue')}")

                    # Check if this looks like real data
                    has_real_teams = any(
                        team in str(sample_game)
                        for team in ["Chiefs", "Bills", "Cowboys", "Patriots"]
                    )
                    has_real_venue = (
                        sample_game.get("venue")
                        and len(sample_game.get("venue", "")) > 10
                    )

                    results["games"] = {
                        "status": (
                            "real"
                            if has_real_teams and has_real_venue
                            else "questionable"
                        ),
                        "count": len(games),
                        "sample": sample_game,
                    }
                else:
                    print("❌ No games found")
                    results["games"] = {"status": "no_data", "count": 0}
            else:
                print(f"❌ Games API failed: {response.status_code}")
                results["games"] = {"status": "failed"}
        except Exception as e:
            print(f"❌ Games API error: {e}")
            results["games"] = {"status": "error", "error": str(e)}

        # 2. Test Odds Data (Should be real Odds API data)
        print("\n💰 TESTING ODDS DATA")
        try:
            response = requests.get(f"{self.base_url}/api/odds/nfl")
            if response.status_code == 200:
                odds_data = response.json()
                odds = odds_data.get("odds", [])

                if odds:
                    sample_odds = odds[0]
                    print(f"✅ Odds API Working: {len(odds)} games with odds")
                    print(
                        f"   Sample: {sample_odds.get('away_team')} @ {sample_odds.get('home_team')}"
                    )

                    if sample_odds.get("bookmakers"):
                        bookmaker = sample_odds["bookmakers"][0]
                        print(f"   Bookmaker: {bookmaker.get('name')}")

                        # Check for real bookmaker names
                        real_books = [
                            "DraftKings",
                            "FanDuel",
                            "BetMGM",
                            "Caesars",
                            "PointsBet",
                        ]
                        has_real_bookmaker = any(
                            book in bookmaker.get("name", "") for book in real_books
                        )

                        results["odds"] = {
                            "status": "real" if has_real_bookmaker else "questionable",
                            "count": len(odds),
                            "bookmakers": len(sample_odds.get("bookmakers", [])),
                            "sample_bookmaker": bookmaker.get("name"),
                        }
                    else:
                        results["odds"] = {
                            "status": "no_bookmakers",
                            "count": len(odds),
                        }
                else:
                    print("❌ No odds found - check Odds API key")
                    results["odds"] = {"status": "no_data", "count": 0}
            else:
                print(f"❌ Odds API failed: {response.status_code}")
                results["odds"] = {"status": "failed"}
        except Exception as e:
            print(f"❌ Odds API error: {e}")
            results["odds"] = {"status": "error", "error": str(e)}

        # 3. Test Basic Fantasy Projections (Original - likely mock)
        print("\n🏈 TESTING BASIC FANTASY PROJECTIONS")
        try:
            response = requests.get(f"{self.base_url}/api/fantasy/projections")
            if response.status_code == 200:
                fantasy_data = response.json()
                projections = fantasy_data.get("projections", [])

                if projections:
                    sample_proj = projections[0]
                    print(
                        f"✅ Basic Fantasy API Working: {len(projections)} projections"
                    )
                    print(
                        f"   Sample: {sample_proj.get('name')} ({sample_proj.get('position')})"
                    )
                    print(f"   Projected Points: {sample_proj.get('projected_points')}")
                    print(f"   Reasoning: {sample_proj.get('reasoning', '')[:50]}...")

                    # Check if reasoning looks generated vs real
                    has_generic_reasoning = any(
                        phrase in sample_proj.get("reasoning", "").lower()
                        for phrase in [
                            "strong matchup",
                            "good volume",
                            "solid projection",
                        ]
                    )

                    results["fantasy_basic"] = {
                        "status": (
                            "likely_mock" if has_generic_reasoning else "questionable"
                        ),
                        "count": len(projections),
                        "sample": sample_proj,
                    }
                else:
                    print("❌ No projections found")
                    results["fantasy_basic"] = {"status": "no_data", "count": 0}
            else:
                print(f"❌ Basic Fantasy API failed: {response.status_code}")
                results["fantasy_basic"] = {"status": "failed"}
        except Exception as e:
            print(f"❌ Basic Fantasy API error: {e}")
            results["fantasy_basic"] = {"status": "error", "error": str(e)}

        # 4. Test Enhanced Fantasy Projections (Should use real stats)
        print("\n🚀 TESTING ENHANCED FANTASY PROJECTIONS (V2)")
        try:
            response = requests.get(f"{self.base_url}/api/fantasy/projections/v2")
            if response.status_code == 200:
                enhanced_data = response.json()
                projections = enhanced_data.get("projections", [])
                data_sources = enhanced_data.get("data_sources", {})

                print(
                    f"✅ Enhanced Fantasy API Working: {len(projections)} projections"
                )
                print(f"   Data Sources:")
                print(f"     - Player Stats: {data_sources.get('player_stats', 0)}")
                print(f"     - Injury Reports: {data_sources.get('injury_reports', 0)}")
                print(f"     - Weather Data: {data_sources.get('weather_data', 0)}")
                print(f"     - Games: {data_sources.get('games', 0)}")

                if projections:
                    sample_proj = projections[0]
                    print(
                        f"   Sample: {sample_proj.get('name')} ({sample_proj.get('position')})"
                    )
                    print(f"   Stats Based: {sample_proj.get('stats_based', False)}")
                    print(
                        f"   Injury Status: {sample_proj.get('injury_status', 'unknown')}"
                    )
                    print(
                        f"   Weather Impact: {sample_proj.get('weather_impact', 'unknown')}"
                    )

                    # Check if this looks like real data
                    has_stats_based = sample_proj.get("stats_based", False)
                    has_injury_data = (
                        sample_proj.get("injury_status", "unknown") != "unknown"
                    )
                    has_weather_data = (
                        sample_proj.get("weather_impact", "unknown") != "unknown"
                    )

                    real_score = sum(
                        [has_stats_based, has_injury_data, has_weather_data]
                    )

                    results["fantasy_enhanced"] = {
                        "status": (
                            "real"
                            if real_score >= 2
                            else "partially_real" if real_score >= 1 else "mock"
                        ),
                        "count": len(projections),
                        "data_sources": data_sources,
                        "features": {
                            "stats_based": has_stats_based,
                            "injury_data": has_injury_data,
                            "weather_data": has_weather_data,
                        },
                    }
                else:
                    print("❌ No enhanced projections found")
                    results["fantasy_enhanced"] = {"status": "no_data", "count": 0}
            else:
                print(f"❌ Enhanced Fantasy API failed: {response.status_code}")
                results["fantasy_enhanced"] = {"status": "failed"}
        except Exception as e:
            print(f"❌ Enhanced Fantasy API error: {e}")
            results["fantasy_enhanced"] = {"status": "error", "error": str(e)}

        # 5. Test Performance Tracking (Should be simulated but structured)
        print("\n📈 TESTING PERFORMANCE TRACKING")
        try:
            response = requests.get(f"{self.base_url}/api/performance/metrics")
            if response.status_code == 200:
                perf_data = response.json()
                metrics = perf_data.get("metrics", {})

                print(f"✅ Performance API Working")
                print(f"   Total Predictions: {metrics.get('total_predictions', 0)}")
                print(f"   Accuracy Rate: {metrics.get('accuracy_rate', 0):.1f}%")
                print(f"   Completed: {metrics.get('completed_predictions', 0)}")

                # Check if metrics look realistic
                accuracy = metrics.get("accuracy_rate", 0)
                total_preds = metrics.get("total_predictions", 0)

                results["performance"] = {
                    "status": (
                        "simulated_realistic"
                        if 50 <= accuracy <= 90 and total_preds > 0
                        else "questionable"
                    ),
                    "metrics": metrics,
                }
            else:
                print(f"❌ Performance API failed: {response.status_code}")
                results["performance"] = {"status": "failed"}
        except Exception as e:
            print(f"❌ Performance API error: {e}")
            results["performance"] = {"status": "error", "error": str(e)}

        # Summary
        print("\n" + "=" * 50)
        print("📋 AUDIT SUMMARY")
        print("=" * 50)

        for endpoint, result in results.items():
            status = result.get("status", "unknown")
            count = result.get("count", "N/A")

            if status == "real":
                emoji = "🟢"
            elif status in ["partially_real", "simulated_realistic"]:
                emoji = "🟡"
            elif status in ["likely_mock", "questionable"]:
                emoji = "🟠"
            else:
                emoji = "🔴"

            print(f"{emoji} {endpoint.upper()}: {status} ({count} items)")

        return results


# Run the audit
if __name__ == "__main__":
    audit = DataAudit()
    asyncio.run(audit.audit_all_endpoints())
