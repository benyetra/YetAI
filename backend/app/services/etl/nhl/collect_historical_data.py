"""
Collect historical NHL data for modeling
Fetches game data, goalie stats, and team stats for the current and past seasons
"""

from app.services.etl.nhl.nhl_api_client import NHLAPIClient
from app.services.etl.nhl._config import _resolve_season, get_nhl_season
from app.services.etl.nhl._db import db_session
from app.models.predictions_models import (
    NHLTeam,
    NHLGoalie,
    NHLTeamStats,
    NHLPlayer,
    NHLGameStats,
    NHLGoalieActuals,
)
from datetime import datetime, timedelta
from collections import defaultdict
import time
import argparse

# All NHL teams
NHL_TEAMS = {
    "ANA": {"id": 24, "name": "Anaheim Ducks"},
    "BOS": {"id": 6, "name": "Boston Bruins"},
    "BUF": {"id": 7, "name": "Buffalo Sabres"},
    "CAR": {"id": 12, "name": "Carolina Hurricanes"},
    "CBJ": {"id": 29, "name": "Columbus Blue Jackets"},
    "CGY": {"id": 20, "name": "Calgary Flames"},
    "CHI": {"id": 16, "name": "Chicago Blackhawks"},
    "COL": {"id": 21, "name": "Colorado Avalanche"},
    "DAL": {"id": 25, "name": "Dallas Stars"},
    "DET": {"id": 17, "name": "Detroit Red Wings"},
    "EDM": {"id": 22, "name": "Edmonton Oilers"},
    "FLA": {"id": 13, "name": "Florida Panthers"},
    "LAK": {"id": 26, "name": "Los Angeles Kings"},
    "MIN": {"id": 30, "name": "Minnesota Wild"},
    "MTL": {"id": 8, "name": "Montreal Canadiens"},
    "NJD": {"id": 1, "name": "New Jersey Devils"},
    "NSH": {"id": 18, "name": "Nashville Predators"},
    "NYI": {"id": 2, "name": "New York Islanders"},
    "NYR": {"id": 3, "name": "New York Rangers"},
    "OTT": {"id": 9, "name": "Ottawa Senators"},
    "PHI": {"id": 4, "name": "Philadelphia Flyers"},
    "PIT": {"id": 5, "name": "Pittsburgh Penguins"},
    "SEA": {"id": 55, "name": "Seattle Kraken"},
    "SJS": {"id": 28, "name": "San Jose Sharks"},
    "STL": {"id": 19, "name": "St. Louis Blues"},
    "TBL": {"id": 14, "name": "Tampa Bay Lightning"},
    "TOR": {"id": 10, "name": "Toronto Maple Leafs"},
    "VAN": {"id": 23, "name": "Vancouver Canucks"},
    "VGK": {"id": 54, "name": "Vegas Golden Knights"},
    "WPG": {"id": 52, "name": "Winnipeg Jets"},
    "WSH": {"id": 15, "name": "Washington Capitals"},
    "UTA": {"id": 59, "name": "Utah Hockey Club"},
}


def populate_teams():
    """Populate the NHL teams table"""
    print("Populating NHL teams...")

    for abbrev, team_info in NHL_TEAMS.items():
        existing_team = (
            db_session.query(NHLTeam).filter_by(team_id=team_info["id"]).first()
        )

        if not existing_team:
            team = NHLTeam(
                team_id=team_info["id"], name=team_info["name"], abbrev=abbrev
            )
            db_session.add(team)
            print(f"Added {team_info['name']}")

    db_session.commit()
    print(f"✓ Added {len(NHL_TEAMS)} teams")


def collect_game_data(season=None, max_games_per_team=20):
    """
    Collect historical game data for all teams
    season: NHL season (e.g., 20252026 for 2024-25 season)
    max_games_per_team: Limit games per team for testing (None = no limit)

    Returns: Number of games collected
    """
    season = _resolve_season(season)
    client = NHLAPIClient()
    print(f"\nCollecting game data for {season} season...")

    games_collected = 0
    game_ids_seen = set()

    for abbrev, team_info in NHL_TEAMS.items():
        print(f"\nProcessing {team_info['name']}...")

        # Get team's schedule
        schedule = client.get_team_schedule(abbrev, season)

        if not schedule or "games" not in schedule:
            print(f"  No schedule found for {abbrev}")
            continue

        # Filter for completed regular season games
        # gameState can be 'FINAL' (recent) or 'OFF' (official/historical)
        completed_games = [
            g
            for g in schedule["games"]
            if g["gameType"] == 2 and g["gameState"] in ["FINAL", "OFF"]
        ]

        # Apply limit if specified
        if max_games_per_team is not None:
            games = completed_games[:max_games_per_team]
        else:
            games = completed_games

        print(f"  Found {len(games)} completed games")

        for game in games:
            game_id = game["id"]

            # Skip if we've already processed this game
            if game_id in game_ids_seen:
                continue

            game_ids_seen.add(game_id)

            # Check if game already exists in DB
            existing_game = (
                db_session.query(NHLGameStats).filter_by(game_id=game_id).first()
            )
            if existing_game:
                continue

            # Fetch detailed boxscore
            boxscore = client.get_game_boxscore(game_id)

            if not boxscore:
                print(f"  ⚠ Could not fetch boxscore for game {game_id}")
                continue

            # Extract goalie data
            home_goalies = (
                boxscore.get("playerByGameStats", {})
                .get("homeTeam", {})
                .get("goalies", [])
            )
            away_goalies = (
                boxscore.get("playerByGameStats", {})
                .get("awayTeam", {})
                .get("goalies", [])
            )

            # Get starting goalies
            home_goalie = next((g for g in home_goalies if g.get("starter")), None)
            away_goalie = next((g for g in away_goalies if g.get("starter")), None)

            # Create game record
            game_stats = NHLGameStats(
                game_id=game_id,
                season=boxscore["season"],
                game_type=boxscore["gameType"],
                game_date=datetime.strptime(boxscore["gameDate"], "%Y-%m-%d").date(),
                game_state=boxscore["gameState"],
                home_team_id=boxscore["homeTeam"]["id"],
                home_team_name=boxscore["homeTeam"]["placeName"]["default"],
                away_team_id=boxscore["awayTeam"]["id"],
                away_team_name=boxscore["awayTeam"]["placeName"]["default"],
                home_score=boxscore["homeTeam"]["score"],
                away_score=boxscore["awayTeam"]["score"],
                home_sog=boxscore["homeTeam"]["sog"],
                away_sog=boxscore["awayTeam"]["sog"],
                venue_name=boxscore["venue"]["default"],
            )

            # Add goalie stats if available
            if home_goalie:
                game_stats.home_goalie_id = home_goalie["playerId"]
                game_stats.home_goalie_name = home_goalie["name"]["default"]
                game_stats.home_goalie_saves = home_goalie.get("saves", 0)
                game_stats.home_goalie_shots_against = home_goalie.get(
                    "shotsAgainst", 0
                )
                game_stats.home_goalie_save_pct = home_goalie.get("savePctg", 0.0)

            if away_goalie:
                game_stats.away_goalie_id = away_goalie["playerId"]
                game_stats.away_goalie_name = away_goalie["name"]["default"]
                game_stats.away_goalie_saves = away_goalie.get("saves", 0)
                game_stats.away_goalie_shots_against = away_goalie.get(
                    "shotsAgainst", 0
                )
                game_stats.away_goalie_save_pct = away_goalie.get("savePctg", 0.0)

            db_session.add(game_stats)
            games_collected += 1

            # Add goalie actuals for modeling
            if home_goalie:
                add_goalie_actual(
                    game_id,
                    boxscore["gameDate"],
                    home_goalie,
                    boxscore["homeTeam"]["placeName"]["default"],
                    boxscore["awayTeam"]["placeName"]["default"],
                )

            if away_goalie:
                add_goalie_actual(
                    game_id,
                    boxscore["gameDate"],
                    away_goalie,
                    boxscore["awayTeam"]["placeName"]["default"],
                    boxscore["homeTeam"]["placeName"]["default"],
                )

            # Collect player stats for shots/goals predictions
            collect_player_game_stats(boxscore)

            # Rate limiting
            time.sleep(0.3)

        # Commit after each team
        db_session.commit()
        print(f"  ✓ Processed {len(games)} games for {abbrev}")

    print(f"\n✓ Collected {games_collected} unique games")
    return games_collected


def add_goalie_actual(game_id, game_date, goalie_data, team_name, opponent_name):
    """Add goalie actual performance to database"""
    actual = NHLGoalieActuals(
        game_id=game_id,
        game_date=datetime.strptime(game_date, "%Y-%m-%d").date(),
        goalie_id=goalie_data["playerId"],
        goalie_name=goalie_data["name"]["default"],
        team_name=team_name,
        opponent_team_name=opponent_name,
        actual_saves=goalie_data.get("saves", 0),
        actual_shots_against=goalie_data.get("shotsAgainst", 0),
        actual_save_pct=goalie_data.get("savePctg", 0.0),
        actual_goals_against=goalie_data.get("goalsAgainst", 0),
        actual_toi=goalie_data.get("toi", "0:00"),
        decision=goalie_data.get("decision", ""),
    )
    db_session.add(actual)


def collect_player_game_stats(boxscore):
    """
    Extract and store individual player stats from a game
    Collects: goals, assists, shots, ice time, +/-, hits, blocks, faceoffs
    """
    game_id = boxscore.get("id")
    game_date = datetime.strptime(boxscore["gameDate"], "%Y-%m-%d").date()

    # Process both teams
    for team_type in ["homeTeam", "awayTeam"]:
        team_data = boxscore["playerByGameStats"][team_type]
        team_name = boxscore[team_type]["placeName"]["default"]
        opponent_name = boxscore["awayTeam" if team_type == "homeTeam" else "homeTeam"][
            "placeName"
        ]["default"]

        # Process forwards and defense
        for position_group in ["forwards", "defense"]:
            if position_group not in team_data:
                continue

            group = team_data[position_group]
            # NHL boxscore API: forwards/defense are lists; older payloads used id-keyed dicts.
            if isinstance(group, dict):
                player_entries = group.items()
            else:
                player_entries = (
                    (p.get("playerId"), p) for p in group if isinstance(p, dict)
                )

            for player_id, player_stats in player_entries:
                if not player_id:
                    player_id = player_stats.get("playerId")
                if not player_id:
                    continue
                # Store player game stats
                # This will be used for: player shots predictions, player goals predictions
                player_game_stat = {
                    "game_id": game_id,
                    "game_date": game_date,
                    "player_id": player_id,
                    "player_name": player_stats["name"]["default"],
                    "team_name": team_name,
                    "opponent_name": opponent_name,
                    "position": player_stats.get(
                        "position", "F" if position_group == "forwards" else "D"
                    ),
                    "goals": player_stats.get("goals", 0),
                    "assists": player_stats.get("assists", 0),
                    "shots": player_stats.get("shots", 0),
                    "hits": player_stats.get("hits", 0),
                    "blocked_shots": player_stats.get("blockedShots", 0),
                    "plus_minus": player_stats.get("plusMinus", 0),
                    "toi": player_stats.get("toi", "0:00"),
                    "pp_goals": player_stats.get("powerPlayGoals", 0),
                    "sh_goals": player_stats.get("shorthandedGoals", 0),
                    "faceoff_pct": player_stats.get("faceoffWinningPctg", 0.0),
                }

                # We'll create a new table for this later
                # For now, just track it in a simple way
                # print(f"  Collected stats for {player_stats['name']['default']}: {player_stats.get('shots', 0)} shots, {player_stats.get('goals', 0)} goals")

    # Return count of players processed
    return True


def calculate_goalie_stats():
    """Calculate aggregated goalie statistics from game data"""
    print("\nCalculating goalie statistics...")

    # Get all goalie actuals
    actuals = db_session.query(NHLGoalieActuals).all()

    # Group by goalie
    goalie_games = defaultdict(list)
    for actual in actuals:
        goalie_games[actual.goalie_id].append(actual)

    goalies_updated = 0

    for goalie_id, games in goalie_games.items():
        if not games:
            continue

        # Sort by date
        games.sort(key=lambda x: x.game_date)

        # Get most recent game info
        latest_game = games[-1]

        # Calculate season stats
        total_saves = sum(g.actual_saves for g in games)
        total_shots = sum(g.actual_shots_against for g in games)
        total_wins = sum(1 for g in games if g.decision == "W")
        total_losses = sum(1 for g in games if g.decision == "L")
        total_ot_losses = sum(1 for g in games if g.decision == "OT")

        # Calculate last 5 and last 10
        last_5 = games[-5:]
        last_10 = games[-10:]

        last_5_saves = sum(g.actual_saves for g in last_5)
        last_5_shots = sum(g.actual_shots_against for g in last_5)

        last_10_saves = sum(g.actual_saves for g in last_10)
        last_10_shots = sum(g.actual_shots_against for g in last_10)

        # Update or create goalie record
        goalie = db_session.query(NHLGoalie).filter_by(player_id=goalie_id).first()

        if not goalie:
            goalie = NHLGoalie(
                player_id=goalie_id,
                name=latest_game.goalie_name,
                team_id=0,  # Will need to look this up
                team_name=latest_game.team_name,
            )
            db_session.add(goalie)

        # Update stats
        goalie.games_played = len(games)
        goalie.wins = total_wins
        goalie.losses = total_losses
        goalie.ot_losses = total_ot_losses
        goalie.saves = total_saves
        goalie.shots_against = total_shots
        goalie.save_pct = total_saves / total_shots if total_shots > 0 else 0
        goalie.goals_against_avg = (
            (total_shots - total_saves) / len(games) if games else 0
        )

        goalie.last_5_saves = last_5_saves
        goalie.last_5_shots_against = last_5_shots
        goalie.last_5_save_pct = last_5_saves / last_5_shots if last_5_shots > 0 else 0
        goalie.last_5_games_played = len(last_5)

        goalie.last_10_saves = last_10_saves
        goalie.last_10_shots_against = last_10_shots
        goalie.last_10_save_pct = (
            last_10_saves / last_10_shots if last_10_shots > 0 else 0
        )
        goalie.last_10_games_played = len(last_10)

        goalie.last_updated = datetime.utcnow()

        goalies_updated += 1

    db_session.commit()
    print(f"✓ Updated {goalies_updated} goalies")


def calculate_team_stats():
    """Calculate aggregated team statistics from game data"""
    print("\nCalculating team statistics...")

    # Get all games
    games = db_session.query(NHLGameStats).filter_by(game_state="FINAL").all()

    # Group by team
    team_games = defaultdict(lambda: {"home": [], "away": []})

    for game in games:
        team_games[game.home_team_id]["home"].append(game)
        team_games[game.away_team_id]["away"].append(game)

    teams_updated = 0

    for team_id, game_lists in team_games.items():
        all_games = game_lists["home"] + game_lists["away"]

        if not all_games:
            continue

        # Sort by date
        all_games.sort(key=lambda x: x.game_date)

        # Calculate stats
        wins = 0
        losses = 0
        ot_losses = 0
        goals_for = 0
        goals_against = 0
        shots_for = 0
        shots_against = 0

        for game in all_games:
            is_home = game.home_team_id == team_id

            if is_home:
                goals_for += game.home_score
                goals_against += game.away_score
                shots_for += game.home_sog
                shots_against += game.away_sog

                if game.home_score > game.away_score:
                    wins += 1
                else:
                    losses += 1
            else:
                goals_for += game.away_score
                goals_against += game.home_score
                shots_for += game.away_sog
                shots_against += game.home_sog

                if game.away_score > game.home_score:
                    wins += 1
                else:
                    losses += 1

        games_played = len(all_games)

        # Last 10 games
        last_10 = all_games[-10:]
        last_10_goals_for = 0
        last_10_goals_against = 0
        last_10_shots_for = 0
        last_10_shots_against = 0

        for game in last_10:
            is_home = game.home_team_id == team_id

            if is_home:
                last_10_goals_for += game.home_score
                last_10_goals_against += game.away_score
                last_10_shots_for += game.home_sog
                last_10_shots_against += game.away_sog
            else:
                last_10_goals_for += game.away_score
                last_10_goals_against += game.home_score
                last_10_shots_for += game.away_sog
                last_10_shots_against += game.home_sog

        # Get team name
        sample_game = all_games[0]
        team_name = (
            sample_game.home_team_name
            if sample_game.home_team_id == team_id
            else sample_game.away_team_name
        )

        # Update or create team stats
        team_stats = db_session.query(NHLTeamStats).filter_by(team_id=team_id).first()

        if not team_stats:
            team_stats = NHLTeamStats(team_id=team_id, team_name=team_name)
            db_session.add(team_stats)

        team_stats.games_played = games_played
        team_stats.wins = wins
        team_stats.losses = losses
        team_stats.ot_losses = ot_losses
        team_stats.goals_for = goals_for
        team_stats.goals_for_per_game = (
            goals_for / games_played if games_played > 0 else 0
        )
        team_stats.goals_against = goals_against
        team_stats.goals_against_per_game = (
            goals_against / games_played if games_played > 0 else 0
        )
        team_stats.shots_for = shots_for
        team_stats.shots_for_per_game = (
            shots_for / games_played if games_played > 0 else 0
        )
        team_stats.shots_against = shots_against
        team_stats.shots_against_per_game = (
            shots_against / games_played if games_played > 0 else 0
        )

        team_stats.last_10_shots_for_per_game = (
            last_10_shots_for / len(last_10) if last_10 else 0
        )
        team_stats.last_10_shots_against_per_game = (
            last_10_shots_against / len(last_10) if last_10 else 0
        )
        team_stats.last_10_goals_for_per_game = (
            last_10_goals_for / len(last_10) if last_10 else 0
        )
        team_stats.last_10_goals_against_per_game = (
            last_10_goals_against / len(last_10) if last_10 else 0
        )

        team_stats.last_updated = datetime.utcnow()

        teams_updated += 1

    db_session.commit()
    print(f"✓ Updated {teams_updated} teams")


def backfill_historical_seasons(start_season=20212022, end_season=None):
    """
    Backfill historical data from multiple seasons
    This populates goalie vs-team history and shot quality metrics

    Args:
        start_season: First season to backfill (e.g., 20212022)
        end_season: Last season to backfill (defaults to NHL_SEASON / get_nhl_season())
    """
    end_season = _resolve_season(end_season)
    print("\n" + "=" * 80)
    print(f"🔄 BACKFILLING HISTORICAL DATA: {start_season} to {end_season}")
    print("=" * 80)

    # Convert season format to years
    start_year = int(str(start_season)[:4])
    end_year = int(str(end_season)[:4])

    total_games = 0

    for year in range(start_year, end_year + 1):
        season = int(f"{year}{year+1}")

        print(f"\n📅 Processing {year}-{str(year+1)[2:]} Season (Season ID: {season})")
        print("-" * 80)

        # Collect all games for this season (no max limit for backfill)
        games_count = collect_game_data(season=season, max_games_per_team=None)
        total_games += games_count

        # Update team stats for this season
        print(f"\n  Calculating team stats for {season}...")
        calculate_team_stats_for_season(season)

        # Collect advanced stats for this season
        print(f"\n  📊 Collecting advanced stats for {season}...")
        update_special_teams_stats(season)
        update_realtime_stats(season)

        # Shot quality only for recent seasons (play-by-play data limited)
        if season >= 20232024:  # Only 2023-24 and later have reliable PBP
            print(f"  🎯 Calculating shot quality metrics for {season}...")
            calculate_shot_quality_metrics(season, sample_games=50)

        # Small delay between seasons to be nice to the API
        time.sleep(2)

    # After all seasons, calculate career goalie stats
    print("\n" + "=" * 80)
    print("📊 Calculating Career Goalie Statistics")
    print("=" * 80)
    calculate_career_goalie_vs_team_stats()

    print("\n" + "=" * 80)
    print(f"✅ BACKFILL COMPLETE: {total_games} total games processed")
    print(f"   - Special teams data collected for all seasons")
    print(f"   - Blocked shots data collected for all seasons")
    print(f"   - Shot quality metrics collected for 2023-24 onward")
    print("=" * 80)


def calculate_team_stats_for_season(season):
    """Calculate team stats for a specific season"""
    print(f"\nCalculating team stats for season {season}...")

    # Get all games for this season
    games = db_session.query(NHLGameStats).filter_by(season=season).all()

    if not games:
        print(f"  No games found for season {season}")
        return

    # Group by team
    team_stats = defaultdict(
        lambda: {
            "games": 0,
            "wins": 0,
            "losses": 0,
            "ot_losses": 0,
            "goals_for": 0,
            "goals_against": 0,
            "shots_for": 0,
            "shots_against": 0,
        }
    )

    for game in games:
        # Home team stats
        team_stats[game.home_team_id]["games"] += 1
        team_stats[game.home_team_id]["goals_for"] += game.home_score
        team_stats[game.home_team_id]["goals_against"] += game.away_score
        team_stats[game.home_team_id]["shots_for"] += game.home_sog
        team_stats[game.home_team_id]["shots_against"] += game.away_sog

        if game.home_score > game.away_score:
            team_stats[game.home_team_id]["wins"] += 1
        else:
            team_stats[game.home_team_id]["losses"] += 1

        # Away team stats
        team_stats[game.away_team_id]["games"] += 1
        team_stats[game.away_team_id]["goals_for"] += game.away_score
        team_stats[game.away_team_id]["goals_against"] += game.home_score
        team_stats[game.away_team_id]["shots_for"] += game.away_sog
        team_stats[game.away_team_id]["shots_against"] += game.home_sog

        if game.away_score > game.home_score:
            team_stats[game.away_team_id]["wins"] += 1
        else:
            team_stats[game.away_team_id]["losses"] += 1

    # Update database
    for team_id, stats in team_stats.items():
        team = db_session.query(NHLTeamStats).filter_by(team_id=team_id).first()
        if team:
            games = stats["games"]
            if games > 0:
                team.goals_for_per_game = stats["goals_for"] / games
                team.goals_against_per_game = stats["goals_against"] / games
                team.shots_for_per_game = stats["shots_for"] / games
                team.shots_against_per_game = stats["shots_against"] / games
                team.shooting_pct = (
                    stats["goals_for"] / stats["shots_for"]
                    if stats["shots_for"] > 0
                    else 0
                )

    db_session.commit()
    print(f"  ✓ Updated stats for {len(team_stats)} teams")


def calculate_career_goalie_vs_team_stats():
    """
    Calculate each goalie's career performance vs. each opponent
    Stores in career_vs_opponent_stats JSON field
    """
    print("\nCalculating career goalie vs. team statistics...")

    goalies = db_session.query(NHLGoalie).all()
    total_updated = 0

    for goalie in goalies:
        # Get all actuals for this goalie
        actuals = (
            db_session.query(NHLGoalieActuals)
            .filter_by(goalie_id=goalie.player_id)
            .all()
        )

        if not actuals:
            continue

        # Group by opponent
        vs_team_stats = defaultdict(lambda: {"games": 0, "saves": 0, "shots": 0})

        for actual in actuals:
            opponent = actual.opponent_team_name
            vs_team_stats[opponent]["games"] += 1
            vs_team_stats[opponent]["saves"] += actual.actual_saves
            vs_team_stats[opponent]["shots"] += actual.actual_shots_against

        # Calculate SV% for each opponent
        career_vs_opponent = {}
        for opponent, stats in vs_team_stats.items():
            if stats["games"] >= 1:  # At least 1 game
                sv_pct = stats["saves"] / stats["shots"] if stats["shots"] > 0 else 0
                career_vs_opponent[opponent] = {
                    "games": stats["games"],
                    "saves": stats["saves"],
                    "shots": stats["shots"],
                    "sv_pct": round(sv_pct, 4),
                }

        if career_vs_opponent:
            goalie.career_vs_opponent_stats = career_vs_opponent
            total_updated += 1

    db_session.commit()
    print(f"  ✓ Updated career vs-team stats for {total_updated} goalies")


def update_special_teams_stats(season=None):
    """
    Update special teams statistics for all teams
    Collects PP%, PK%, PPO/game, etc. from NHL API
    """
    season = _resolve_season(season)
    print(f"\nUpdating special teams stats for season {season}...")

    client = NHLAPIClient()
    special_teams_data = client.get_team_special_teams_stats(season)

    if not special_teams_data or "data" not in special_teams_data:
        print("  ❌ No special teams data available")
        return

    teams_updated = 0

    for team_data in special_teams_data["data"]:
        team_id = team_data["teamId"]
        team_stats = db_session.query(NHLTeamStats).filter_by(team_id=team_id).first()

        if not team_stats:
            # Create new team stats record if it doesn't exist
            team_stats = NHLTeamStats(
                team_id=team_id, team_name=team_data["teamFullName"]
            )
            db_session.add(team_stats)

        # Update special teams fields
        team_stats.power_play_pct = team_data.get("powerPlayPct", 0.0)
        team_stats.penalty_kill_pct = team_data.get("penaltyKillPct", 0.0)

        # Calculate PP opportunities per game
        games_played = team_data.get("gamesPlayed", 1)
        if games_played > 0:
            # Estimate PPO from PP% and goals
            pp_goals = (
                team_data.get("powerPlayNetPct", 0) * games_played * 3
            )  # Rough estimate
            pp_pct = team_data.get("powerPlayPct", 0.20)
            if pp_pct > 0:
                team_stats.pp_opportunities_per_game = (
                    (pp_goals / pp_pct) / games_played if pp_pct > 0 else 3.0
                )
            else:
                team_stats.pp_opportunities_per_game = 3.0  # League average

        teams_updated += 1

    db_session.commit()
    print(f"  ✓ Updated special teams stats for {teams_updated} teams")


def update_realtime_stats(season=None):
    """
    Update realtime statistics including blocked shots
    """
    season = _resolve_season(season)
    print(f"\nUpdating realtime stats (blocked shots, etc.) for season {season}...")

    client = NHLAPIClient()
    realtime_data = client.get_team_realtime_stats(season)

    if not realtime_data or "data" not in realtime_data:
        print("  ❌ No realtime data available")
        return

    teams_updated = 0

    for team_data in realtime_data["data"]:
        team_id = team_data["teamId"]
        team_stats = db_session.query(NHLTeamStats).filter_by(team_id=team_id).first()

        if not team_stats:
            continue

        # Update blocked shots per game
        games_played = team_data.get("gamesPlayed", 1)
        blocked_shots = team_data.get("blockedShots", 0)

        if games_played > 0:
            team_stats.blocked_shots_per_game = blocked_shots / games_played

        teams_updated += 1

    db_session.commit()
    print(f"  ✓ Updated realtime stats for {teams_updated} teams")


def calculate_shot_quality_metrics(season=None, sample_games=50):
    """
    Calculate shot quality metrics from play-by-play data
    Uses a sample of recent games to avoid API overload

    Args:
        season: Season to analyze
        sample_games: Number of recent games to sample per team
    """
    season = _resolve_season(season)
    print(f"\nCalculating shot quality metrics for season {season}...")
    print(f"  (Sampling {sample_games} recent games per team)")

    client = NHLAPIClient()

    # Get recent games for shot quality analysis
    import math

    team_shot_data = defaultdict(
        lambda: {"total_distance": 0, "shot_count": 0, "high_danger": 0}
    )

    # Sample games from the database
    recent_games = (
        db_session.query(NHLGameStats)
        .filter_by(season=season)
        .order_by(NHLGameStats.game_date.desc())
        .limit(sample_games)
        .all()
    )

    games_analyzed = 0

    for game in recent_games:
        # Get play-by-play data
        pbp_data = client.get_game_play_by_play(game.game_id)

        if not pbp_data or "plays" not in pbp_data:
            continue

        # Analyze shots
        for play in pbp_data["plays"]:
            if play.get("typeDescKey") == "shot-on-goal":
                details = play.get("details", {})
                x_coord = details.get("xCoord", 0)
                y_coord = details.get("yCoord", 0)
                team_id = details.get("eventOwnerTeamId")

                # Calculate shot distance from net (net is at x=89 for offensive zone)
                # Distance = sqrt((89 - x)^2 + y^2)
                distance = math.sqrt((89 - abs(x_coord)) ** 2 + y_coord**2)

                if team_id:
                    team_shot_data[team_id]["total_distance"] += distance
                    team_shot_data[team_id]["shot_count"] += 1

                    # High danger = within 20 feet and in slot (|y| < 20)
                    if distance < 20 and abs(y_coord) < 20:
                        team_shot_data[team_id]["high_danger"] += 1

        games_analyzed += 1

        # Rate limiting
        time.sleep(0.5)

        if games_analyzed % 10 == 0:
            print(f"    Analyzed {games_analyzed}/{len(recent_games)} games...")

    # Update team stats
    teams_updated = 0

    for team_id, shot_data in team_shot_data.items():
        team_stats = db_session.query(NHLTeamStats).filter_by(team_id=team_id).first()

        if team_stats and shot_data["shot_count"] > 0:
            # Average shot distance
            team_stats.avg_shot_distance = (
                shot_data["total_distance"] / shot_data["shot_count"]
            )

            # High danger chances per game
            team_stats.high_danger_chances_against_per_game = (
                shot_data["high_danger"] / games_analyzed if games_analyzed > 0 else 0
            )

            teams_updated += 1

    db_session.commit()
    print(
        f"  ✓ Updated shot quality metrics for {teams_updated} teams from {games_analyzed} games"
    )


def collect_season_player_stats(season=None):
    """
    Collect season-long player statistics for all skaters
    This provides baseline data for player shots/goals predictions
    """
    season = _resolve_season(season)
    print(f"\nCollecting season player stats for {season}...")

    client = NHLAPIClient()
    skater_data = client.get_skater_stats(season)

    if not skater_data or "data" not in skater_data:
        print("  ❌ No skater data available")
        return

    # Create team abbreviation to ID mapping
    team_abbrev_to_id = {abbrev: info["id"] for abbrev, info in NHL_TEAMS.items()}
    team_abbrev_to_name = {abbrev: info["name"] for abbrev, info in NHL_TEAMS.items()}

    players_updated = 0

    for player_stats in skater_data["data"]:
        player_id = player_stats["playerId"]
        team_abbrevs = player_stats.get("teamAbbrevs", "")

        # Handle players who played for multiple teams (e.g., "TOR,VAN")
        # Use the last team (most recent)
        if "," in team_abbrevs:
            team_abbrev = team_abbrevs.split(",")[-1].strip()
        else:
            team_abbrev = team_abbrevs

        # Get team ID and name
        team_id = team_abbrev_to_id.get(team_abbrev, 0)
        team_name = team_abbrev_to_name.get(team_abbrev, "Unknown")

        # Skip if we can't map the team (shouldn't happen with our comprehensive list)
        if team_id == 0:
            print(
                f"  ⚠️  Could not map team '{team_abbrev}' for {player_stats['skaterFullName']}"
            )
            continue

        # Find or create player record
        player = db_session.query(NHLPlayer).filter_by(player_id=player_id).first()

        if not player:
            player = NHLPlayer(
                player_id=player_id,
                name=player_stats["skaterFullName"],
                team_id=team_id,
                team_name=team_name,
                position=player_stats.get("positionCode", "F"),
            )
            db_session.add(player)
        else:
            # Update team info (in case of trades)
            player.team_id = team_id
            player.team_name = team_name

        # Update season stats
        player.games_played = player_stats.get("gamesPlayed", 0)
        player.goals = player_stats.get("goals", 0)
        player.assists = player_stats.get("assists", 0)
        player.points = player_stats.get("points", 0)
        player.shots = player_stats.get("shots", 0)
        player.toi_per_game = player_stats.get("timeOnIcePerGame", 0.0)

        # Calculate per-game averages
        games = player.games_played or 1
        player.shots_per_game = player.shots / games

        player.last_updated = datetime.utcnow()
        players_updated += 1

    db_session.commit()
    print(f"  ✓ Updated {players_updated} players")


def collect_team_offensive_stats(season=None):
    """
    Collect detailed team offensive statistics
    Used for: team total goals predictions, over/under predictions
    """
    season = _resolve_season(season)
    print(f"\nCollecting team offensive stats for {season}...")

    # Get all games for the season
    games = db_session.query(NHLGameStats).filter_by(season=season).all()

    if not games:
        print("  ❌ No games found for season")
        return

    # Calculate team offensive metrics
    team_offense = defaultdict(
        lambda: {
            "games": 0,
            "goals": 0,
            "shots": 0,
            "pp_goals": 0,
            "home_goals": 0,
            "away_goals": 0,
            "goals_period_1": 0,
            "goals_period_2": 0,
            "goals_period_3": 0,
        }
    )

    for game in games:
        # Home team
        team_offense[game.home_team_id]["games"] += 1
        team_offense[game.home_team_id]["goals"] += game.home_score
        team_offense[game.home_team_id]["shots"] += game.home_sog
        team_offense[game.home_team_id]["home_goals"] += game.home_score

        # Away team
        team_offense[game.away_team_id]["games"] += 1
        team_offense[game.away_team_id]["goals"] += game.away_score
        team_offense[game.away_team_id]["shots"] += game.away_sog
        team_offense[game.away_team_id]["away_goals"] += game.away_score

    # Update team stats
    teams_updated = 0
    for team_id, stats in team_offense.items():
        team = db_session.query(NHLTeamStats).filter_by(team_id=team_id).first()
        if team and stats["games"] > 0:
            # Already have goals_for_per_game, but add more detail
            team.home_goals_per_game = (
                stats["home_goals"] / (stats["games"] / 2) if stats["games"] > 0 else 0
            )
            team.away_goals_per_game = (
                stats["away_goals"] / (stats["games"] / 2) if stats["games"] > 0 else 0
            )

            # Calculate shooting percentage (goals / shots)
            if stats["shots"] > 0:
                team.shooting_pct = stats["goals"] / stats["shots"]

            teams_updated += 1

    db_session.commit()
    print(f"  ✓ Updated offensive stats for {teams_updated} teams")


def update_daily_stats(season=None):
    """
    Daily update function - updates ALL stats with latest data
    This should be run daily to keep stats current

    Includes:
    - Team special teams (PP%, PK%)
    - Team defensive stats (blocked shots, shot quality)
    - Player season stats (goals, shots, ice time)
    - Team offensive trends
    """
    season = _resolve_season(season)
    print("\n" + "=" * 80)
    print(f"📅 DAILY STATS UPDATE - Season {season}")
    print("=" * 80)

    # Update special teams stats (PP%, PK%)
    update_special_teams_stats(season)

    # Update realtime stats (blocked shots)
    update_realtime_stats(season)

    # Update shot quality metrics (sample recent games)
    calculate_shot_quality_metrics(season, sample_games=30)

    # Recalculate team stats from game data
    calculate_team_stats()

    # NEW: Collect player stats for shots/goals predictions
    collect_season_player_stats(season)

    # NEW: Update team offensive stats for totals predictions
    collect_team_offensive_stats(season)

    print("\n" + "=" * 80)
    print("✅ Daily update complete!")
    print("   - Team stats updated (special teams, defense, offense)")
    print("   - Player stats updated (all skaters)")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Collect NHL historical data")
    parser.add_argument(
        "--backfill", action="store_true", help="Backfill data from 2021-2025 seasons"
    )
    parser.add_argument(
        "--start-season",
        type=int,
        default=20212022,
        help="Starting season for backfill (default: 20212022)",
    )
    parser.add_argument(
        "--end-season",
        type=int,
        default=None,
        help=f"Ending season for backfill (default: NHL_SEASON / {get_nhl_season()})",
    )
    parser.add_argument(
        "--daily-update",
        action="store_true",
        help="Run daily stats update (special teams, blocked shots, shot quality)",
    )
    parser.add_argument(
        "--current-only",
        action="store_true",
        help="Only collect current season data (default behavior)",
    )

    args = parser.parse_args()

    print("=" * 80)
    print("NHL Historical Data Collection")
    print("=" * 80)

    # Step 1: Populate teams
    populate_teams()

    current_season = get_nhl_season()

    if args.daily_update:
        # Daily update mode: update stats only
        update_daily_stats(current_season)
    elif args.backfill:
        # Backfill mode: collect multiple seasons
        backfill_historical_seasons(args.start_season, args.end_season)

        # After backfill, update advanced stats for current season
        print("\n📊 Updating advanced statistics for current season...")
        update_special_teams_stats(current_season)
        update_realtime_stats(current_season)
        calculate_shot_quality_metrics(current_season, sample_games=50)
        collect_season_player_stats(current_season)
        collect_team_offensive_stats(current_season)
    else:
        # Default mode: current season only
        print("\n💡 Tip: Use --backfill to load historical data from 2021-2025")
        print("   This will improve goalie vs-team history and shot quality metrics")
        print("\n💡 Tip: Use --daily-update to update team stats daily\n")

        # Step 2: Collect game data (current season)
        collect_game_data(season=current_season, max_games_per_team=20)

        # Step 3: Calculate goalie stats
        calculate_goalie_stats()

        # Step 4: Calculate team stats
        calculate_team_stats()

        # Step 5: Update advanced stats (all types)
        update_special_teams_stats(current_season)
        update_realtime_stats(current_season)
        calculate_shot_quality_metrics(current_season, sample_games=20)
        collect_season_player_stats(current_season)
        collect_team_offensive_stats(current_season)

    print("\n" + "=" * 80)
    print("✓ Data collection complete!")
    print("=" * 80)


if __name__ == "__main__":
    main()


def run_ingest(season: int | None = None) -> dict:
    from app.services.etl.nhl._db import close_session, init_session

    season = _resolve_season(season)
    init_session()
    try:
        populate_teams()
        collect_game_data(season=season, max_games_per_team=20)
        calculate_goalie_stats()
        calculate_team_stats()
        update_special_teams_stats(season)
        update_realtime_stats(season)
        calculate_shot_quality_metrics(season, sample_games=20)
        collect_season_player_stats(season)
        collect_team_offensive_stats(season)
        return {"status": "ok", "task": "nhl_ingest", "season": season}
    finally:
        close_session()


def run_update_daily_stats(season: int | None = None) -> dict:
    from app.services.etl.nhl._db import close_session, init_session

    season = _resolve_season(season)
    init_session()
    try:
        update_daily_stats(season=season)
        return {"status": "ok", "task": "nhl_update_daily_stats", "season": season}
    finally:
        close_session()
