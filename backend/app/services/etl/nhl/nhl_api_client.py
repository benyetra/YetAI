"""
NHL API Client
Handles all API calls to the NHL Stats API
"""

import requests
from datetime import datetime, timedelta
import time


class NHLAPIClient:
    def __init__(self):
        self.base_url = "https://api-web.nhle.com/v1"
        self.stats_url = "https://api.nhle.com/stats/rest/en"

    def get_schedule(self, date=None):
        """
        Get schedule for a specific date
        date format: YYYY-MM-DD (defaults to today)
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        url = f"{self.base_url}/schedule/{date}"
        response = requests.get(url)

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching schedule: {response.status_code}")
            return None

    def get_team_schedule(self, team_abbrev, season):
        """
        Get full season schedule for a team
        team_abbrev: Team abbreviation (e.g., 'BOS', 'TOR')
        season: Season in format YYYYYYY (e.g., 20252026)
        """
        url = f"{self.base_url}/club-schedule-season/{team_abbrev}/{season}"
        response = requests.get(url)

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching team schedule: {response.status_code}")
            return None

    def get_game_boxscore(self, game_id):
        """
        Get detailed boxscore for a specific game
        game_id: NHL game ID (e.g., 2024020001)
        """
        url = f"{self.base_url}/gamecenter/{game_id}/boxscore"
        response = requests.get(url)

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching boxscore: {response.status_code}")
            return None

    def get_team_stats(self, season=None):
        """
        Get team statistics
        season: Season ID (e.g., 20252026)
        """
        url = f"{self.stats_url}/team/summary"
        if season:
            url += f"?cayenneExp=seasonId={season}"

        response = requests.get(url)

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching team stats: {response.status_code}")
            return None

    def get_standings(self):
        """Get current NHL standings"""
        url = f"{self.base_url}/standings/now"
        response = requests.get(url)

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching standings: {response.status_code}")
            return None

    def get_player_stats(self, player_id):
        """
        Get individual player statistics
        player_id: NHL player ID
        """
        url = f"{self.base_url}/player/{player_id}/landing"
        response = requests.get(url)

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching player stats: {response.status_code}")
            return None

    def get_team_roster(self, team_abbrev):
        """
        Get current roster for a team
        team_abbrev: Team abbreviation (e.g., 'BOS', 'TOR')
        """
        url = f"{self.base_url}/roster/{team_abbrev}/current"
        response = requests.get(url)

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching roster: {response.status_code}")
            return None

    def get_historical_games(self, team_abbrev, season, game_type=2):
        """
        Get all games for a team in a season
        team_abbrev: Team abbreviation
        season: Season (e.g., 20252026)
        game_type: 1=preseason, 2=regular, 3=playoffs
        """
        schedule = self.get_team_schedule(team_abbrev, season)

        if not schedule or "games" not in schedule:
            return []

        games = [g for g in schedule["games"] if g["gameType"] == game_type]
        return games

    def get_game_details_batch(self, game_ids, delay=0.5):
        """
        Fetch multiple game boxscores with rate limiting
        game_ids: List of game IDs
        delay: Seconds to wait between requests
        """
        results = []

        for game_id in game_ids:
            boxscore = self.get_game_boxscore(game_id)
            if boxscore:
                results.append(boxscore)
            time.sleep(delay)

        return results

    def get_team_special_teams_stats(self, season=None):
        """
        Get special teams statistics (PP%, PK%, etc.)
        season: Season ID (e.g., 20252026)
        """
        url = f"{self.stats_url}/team/summary"
        if season:
            url += f"?cayenneExp=seasonId={season}"

        response = requests.get(url)

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching special teams stats: {response.status_code}")
            return None

    def get_team_realtime_stats(self, season=None):
        """
        Get realtime team statistics (blocked shots, hits, etc.)
        season: Season ID (e.g., 20252026)
        """
        url = f"{self.stats_url}/team/realtime"
        if season:
            url += f"?cayenneExp=seasonId={season}"

        response = requests.get(url)

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching realtime stats: {response.status_code}")
            return None

    def get_game_play_by_play(self, game_id):
        """
        Get play-by-play data for shot quality analysis
        game_id: NHL game ID (e.g., 2024020001)
        """
        url = f"{self.base_url}/gamecenter/{game_id}/play-by-play"
        response = requests.get(url)

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching play-by-play: {response.status_code}")
            return None

    def get_skater_stats(self, season=None):
        """
        Get all skater statistics (goals, assists, shots, ice time, etc.)
        season: Season ID (e.g., 20252026)
        """
        url = f"{self.stats_url}/skater/summary"
        if season:
            url += f"?cayenneExp=seasonId={season}%20and%20gameTypeId=2"

        response = requests.get(url)

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching skater stats: {response.status_code}")
            return None

    def get_player_game_log(self, player_id, season, game_type=2):
        """
        Get game-by-game stats for a player
        player_id: NHL player ID
        season: Season (e.g., 20252026)
        game_type: 2 for regular season, 3 for playoffs
        """
        url = f"{self.base_url}/player/{player_id}/game-log/{season}/{game_type}"
        response = requests.get(url)

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching player game log: {response.status_code}")
            return None

    def get_team_scoring_leaders(self, team_abbrev):
        """
        Get top scorers for a team
        team_abbrev: Team abbreviation (e.g., 'BOS')
        """
        url = f"{self.base_url}/club-stats/{team_abbrev}/now"
        response = requests.get(url)

        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching team leaders: {response.status_code}")
            return None


if __name__ == "__main__":
    # Test the API client
    client = NHLAPIClient()

    print("Testing schedule endpoint...")
    schedule = client.get_schedule()
    if schedule:
        print(f"Found {len(schedule.get('gameWeek', []))} games")

    print("\nTesting boxscore endpoint...")
    boxscore = client.get_game_boxscore(2024020001)
    if boxscore:
        print(
            f"Game: {boxscore['awayTeam']['abbrev']} @ {boxscore['homeTeam']['abbrev']}"
        )
        print(
            f"Score: {boxscore['awayTeam']['score']} - {boxscore['homeTeam']['score']}"
        )
