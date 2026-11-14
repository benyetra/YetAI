"""
Collect historical NHL data for modeling
Fetches game data, goalie stats, and team stats for the current and past seasons
"""

from app.services.etl.nhl.nhl_api_client import NHLAPIClient
from app.services.etl.nba._espn import now_eastern
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
    # Utah Hockey Club was id 59 in 2024-25; the Mammoth are 68 from 2025-26 on.
    "UTA": {"id": 68, "name": "Utah Mammoth"},
}

# Shrinkage: current-season totals are blended with a prior worth this many
# games (teams, skaters) or shots against (goalies) of last-season evidence.
# Chosen by scripts/nhl_backtest_2026.py (2026-27 as-of backtest): K=40 gave the best
# totals MAE/correlation and matched the best saves inputs; the prior is the team's
# last-season rate scaled to this season's league level, and that level is itself
# shrunk toward last season's by LEAGUE_PRIOR_TEAM_GAMES team-games.
TEAM_PRIOR_GAMES = 40
LEAGUE_PRIOR_TEAM_GAMES = 64
SKATER_PRIOR_GAMES = 10
GOALIE_PRIOR_SHOTS = 300
DEFAULT_LEAGUE_SAVE_PCT = 0.905  # only when no goalie has a current shot yet
FINISHED_STATES = ("OFF", "FINAL")
# NHL ids: one season is 10001 apart (20262027 - 10001 = 20252026).
PRIOR_SEASON_STEP = 10001


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


def collect_game_data(season=None, max_games_per_team=None):
    """
    Collect finished regular-season/playoff games not yet stored (incremental).
    season: NHL season id (default: current, e.g. 20262027)
    max_games_per_team: optional cap for testing (None = no cap)

    Returns: Number of games collected
    """
    season = _resolve_season(season)
    client = NHLAPIClient()
    print(f"\nCollecting game data for {season} season...")

    games_collected = 0
    stored_ids = {row[0] for row in db_session.query(NHLGameStats.game_id).all()}

    for abbrev, team_info in NHL_TEAMS.items():
        print(f"\nProcessing {team_info['name']}...")

        # Get team's schedule
        schedule = client.get_team_schedule(abbrev, season)

        if not schedule or "games" not in schedule:
            print(f"  No schedule found for {abbrev}")
            continue

        # Finished regular-season (2) and playoff (3) games; preseason (1) is
        # not NHL evidence. Finished is "OFF" (official) or briefly "FINAL".
        completed_games = [
            g
            for g in schedule["games"]
            if g["gameType"] in (2, 3) and g["gameState"] in FINISHED_STATES
        ]

        if max_games_per_team is not None:
            games = completed_games[:max_games_per_team]
        else:
            games = completed_games

        print(f"  Found {len(games)} completed games")

        for game in games:
            game_id = game["id"]

            # Skip games already stored (also covers the other team's schedule)
            if game_id in stored_ids:
                continue
            stored_ids.add(game_id)

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
    """Add goalie actual performance unless (game_id, goalie_id) is already stored"""
    exists = (
        db_session.query(NHLGoalieActuals.id)
        .filter_by(game_id=game_id, goalie_id=goalie_data["playerId"])
        .first()
    )
    if exists:
        return
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


def _in_season(game_id, season):
    """True for a regular-season (type 02) game id of ``season`` (ids: YYYYTTNNNN)."""
    return game_id // 1_000_000 == season // 10000 and (game_id // 10_000) % 100 == 2


def _pct(saves, shots):
    return saves / shots if shots > 0 else None


def calculate_goalie_stats(season=None):
    """Rebuild pred_nhl_goalies from the CURRENT season's regular-season games.

    ``save_pct`` is shrunk toward the goalie's last regular-season save pct (or
    the league's when he faced < GOALIE_PRIOR_SHOTS) so a 2-game goalie is not
    read at face value. Goalies without a current game keep their row with
    games_played 0 and save_pct NULL; last_game_* stay true dates.
    """
    season = _resolve_season(season)
    today = now_eastern().date()
    print(f"\nCalculating goalie statistics for {season}...")

    by_goalie = defaultdict(list)
    for actual in db_session.query(NHLGoalieActuals).all():
        by_goalie[actual.goalie_id].append(actual)

    # Team + home/away from the stored game rows (starters only)
    game_rows = {g.game_id: g for g in db_session.query(NHLGameStats).all()}
    latest_team = {}  # goalie_id -> (game_date, game_id, team_id, team_name)
    for g in game_rows.values():
        for gid, tid, tname in (
            (g.home_goalie_id, g.home_team_id, g.home_team_name),
            (g.away_goalie_id, g.away_team_id, g.away_team_name),
        ):
            key = (g.game_date, g.game_id)
            if gid and (gid not in latest_team or key > latest_team[gid][:2]):
                latest_team[gid] = (g.game_date, g.game_id, tid, tname)

    def is_home(actual):
        if actual.is_home is not None:
            return actual.is_home
        row = game_rows.get(actual.game_id)
        return bool(row and row.home_goalie_id == actual.goalie_id)

    # League save pct this season: the prior of last resort
    league_saves = league_shots = 0
    for games in by_goalie.values():
        for a in games:
            if _in_season(a.game_id, season):
                league_saves += a.actual_saves
                league_shots += a.actual_shots_against
    league_sv = _pct(league_saves, league_shots) or DEFAULT_LEAGUE_SAVE_PCT

    goalies_updated = 0

    for goalie_id, all_games in by_goalie.items():
        all_games.sort(key=lambda x: (x.game_date, x.game_id))
        latest_game = all_games[-1]
        games = [g for g in all_games if _in_season(g.game_id, season)]

        prior_saves = prior_shots = 0
        for g in all_games:
            if _in_season(g.game_id, season - PRIOR_SEASON_STEP):
                prior_saves += g.actual_saves
                prior_shots += g.actual_shots_against
        prior_sv = (
            prior_saves / prior_shots
            if prior_shots >= GOALIE_PRIOR_SHOTS
            else league_sv
        )

        goalie = db_session.query(NHLGoalie).filter_by(player_id=goalie_id).first()
        team = latest_team.get(goalie_id)
        if not goalie:
            goalie = NHLGoalie(
                player_id=goalie_id,
                name=latest_game.goalie_name,
                team_id=team[2] if team else 0,
                team_name=team[3] if team else latest_game.team_name,
            )
            db_session.add(goalie)
        elif team:
            goalie.team_id, goalie.team_name = team[2], team[3]

        total_saves = sum(g.actual_saves for g in games)
        total_shots = sum(g.actual_shots_against for g in games)
        last_5, last_10 = games[-5:], games[-10:]
        home = [g for g in games if is_home(g)]
        away = [g for g in games if not is_home(g)]

        goalie.games_played = len(games)
        goalie.wins = sum(1 for g in games if g.decision == "W")
        goalie.losses = sum(1 for g in games if g.decision == "L")
        goalie.ot_losses = sum(1 for g in games if g.decision in ("OT", "O"))
        goalie.saves = total_saves
        goalie.shots_against = total_shots
        goalie.save_pct = (
            (total_saves + GOALIE_PRIOR_SHOTS * prior_sv)
            / (total_shots + GOALIE_PRIOR_SHOTS)
            if games
            else None
        )
        goalie.goals_against_avg = (
            (total_shots - total_saves) / len(games) if games else None
        )

        for prefix, rows in (("last_5", last_5), ("last_10", last_10)):
            saves = sum(g.actual_saves for g in rows)
            shots = sum(g.actual_shots_against for g in rows)
            setattr(goalie, f"{prefix}_saves", saves)
            setattr(goalie, f"{prefix}_shots_against", shots)
            setattr(goalie, f"{prefix}_save_pct", _pct(saves, shots))
            setattr(goalie, f"{prefix}_games_played", len(rows))
        for prefix, rows in (("home", home), ("away", away)):
            saves = sum(g.actual_saves for g in rows)
            shots = sum(g.actual_shots_against for g in rows)
            setattr(goalie, f"{prefix}_saves", saves)
            setattr(goalie, f"{prefix}_shots_against", shots)
            setattr(goalie, f"{prefix}_save_pct", _pct(saves, shots))
            setattr(goalie, f"{prefix}_games_played", len(rows))

        goalie.last_game_date = latest_game.game_date
        goalie.last_game_saves = latest_game.actual_saves
        goalie.last_game_shots = latest_game.actual_shots_against
        goalie.games_in_last_7_days = sum(
            1 for g in all_games if 0 <= (today - g.game_date).days < 7
        )

        goalie.last_updated = datetime.utcnow()

        goalies_updated += 1

    db_session.commit()
    print(f"✓ Updated {goalies_updated} goalies")


def _team_games(season):
    """team_id -> that team's finished regular-season games of ``season`` by date."""
    games = (
        db_session.query(NHLGameStats)
        .filter(
            NHLGameStats.season == season,
            NHLGameStats.game_type == 2,
            NHLGameStats.game_state.in_(FINISHED_STATES),
        )
        .order_by(NHLGameStats.game_date, NHLGameStats.game_id)
        .all()
    )
    out = defaultdict(list)
    for g in games:
        if g.home_score is None or g.away_score is None:
            continue
        home_sog, away_sog = g.home_sog or 0, g.away_sog or 0
        out[g.home_team_id].append(
            dict(gf=g.home_score, ga=g.away_score, sf=home_sog, sa=away_sog)
            | {"home": True, "name": g.home_team_name}
        )
        out[g.away_team_id].append(
            dict(gf=g.away_score, ga=g.home_score, sf=away_sog, sa=home_sog)
            | {"home": False, "name": g.away_team_name}
        )
    return out


def _per_game(rows):
    """Mean gf/ga/sf/sa per game over a team's game dicts (None when no games)."""
    if not rows:
        return None
    return {k: sum(r[k] for r in rows) / len(rows) for k in ("gf", "ga", "sf", "sa")}


_TEAM_RATE_COLUMNS = {
    "gf": "goals_for_per_game",
    "ga": "goals_against_per_game",
    "sf": "shots_for_per_game",
    "sa": "shots_against_per_game",
}
_TEAM_LAST10_COLUMNS = {
    "gf": "last_10_goals_for_per_game",
    "ga": "last_10_goals_against_per_game",
    "sf": "last_10_shots_for_per_game",
    "sa": "last_10_shots_against_per_game",
}


def _league_level(current, previous):
    """Per-team-game league means this season, shrunk toward last season's."""
    now = [r for rows in current.values() for r in rows]
    prev = _per_game([r for rows in previous.values() for r in rows])
    if prev is None:
        return _per_game(now)
    k = LEAGUE_PRIOR_TEAM_GAMES
    return {
        key: (sum(r[key] for r in now) + k * prev[key]) / (len(now) + k)
        for key in _TEAM_RATE_COLUMNS
    }


def _team_prior(previous, team_id, league):
    """Last season's rate for team_id scaled to this season's league level."""
    mine = _per_game(previous.get(team_id))
    prev = _per_game([r for rows in previous.values() for r in rows])
    if mine is None or prev is None:
        return league
    return {
        key: mine[key] * league[key] / prev[key] if prev[key] else league[key]
        for key in _TEAM_RATE_COLUMNS
    }


def calculate_team_stats(season=None):
    """Rebuild pred_nhl_team_stats from the CURRENT season's regular-season games.

    Totals are raw. Per-game rates are shrunk toward a prior:
    ``(total + K * prior) / (games + K)``, K = TEAM_PRIOR_GAMES, where prior is the
    same team_id's last-season rate times (league level now / league level last
    season), or the league level when the team has no last-season games stored.
    The league level is this season's per-team-game mean shrunk toward last
    season's by LEAGUE_PRIOR_TEAM_GAMES. last_10_* are raw.
    Teams with no current games get games_played 0 and NULL rates so they never
    feed a league average.
    """
    season = _resolve_season(season)
    print(f"\nCalculating team statistics for {season}...")

    current = _team_games(season)
    previous = _team_games(season - PRIOR_SEASON_STEP)
    league = _league_level(current, previous)

    existing = {t.team_id: t for t in db_session.query(NHLTeamStats).all()}
    teams_updated = 0

    for team_id in set(existing) | set(current):
        rows = current.get(team_id, [])
        team_stats = existing.get(team_id)
        if team_stats is None:
            team_stats = NHLTeamStats(team_id=team_id, team_name=rows[-1]["name"])
            db_session.add(team_stats)

        n = len(rows)
        team_stats.games_played = n
        team_stats.wins = sum(1 for r in rows if r["gf"] > r["ga"])
        team_stats.losses = n - team_stats.wins
        team_stats.ot_losses = 0
        totals = {k: sum(r[k] for r in rows) for k in _TEAM_RATE_COLUMNS}
        team_stats.goals_for = totals["gf"]
        team_stats.goals_against = totals["ga"]
        team_stats.shots_for = totals["sf"]
        team_stats.shots_against = totals["sa"]

        if n == 0:
            for column in (
                *_TEAM_RATE_COLUMNS.values(),
                *_TEAM_LAST10_COLUMNS.values(),
            ):
                setattr(team_stats, column, None)
            team_stats.shooting_pct = None
            team_stats.last_10_shooting_pct = None
        else:
            prior = _team_prior(previous, team_id, league)
            for key, column in _TEAM_RATE_COLUMNS.items():
                setattr(
                    team_stats,
                    column,
                    (totals[key] + TEAM_PRIOR_GAMES * prior[key])
                    / (n + TEAM_PRIOR_GAMES),
                )
            last_10 = _per_game(rows[-10:])
            for key, column in _TEAM_LAST10_COLUMNS.items():
                setattr(team_stats, column, last_10[key])
            team_stats.shooting_pct = _pct(totals["gf"], totals["sf"])
            last_10_rows = rows[-10:]
            team_stats.last_10_shooting_pct = _pct(
                sum(r["gf"] for r in last_10_rows), sum(r["sf"] for r in last_10_rows)
            )
            teams_updated += 1

        team_stats.last_updated = datetime.utcnow()

    db_session.commit()
    print(f"✓ Updated {teams_updated} teams ({len(existing)} rows checked)")


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
    """Calculate team stats for a specific season (same rules as calculate_team_stats)"""
    calculate_team_stats(season)


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
    This provides baseline data for player shots/goals predictions.

    ``shots_per_game`` is shrunk: ``(shots + K*prior) / (games + K)`` with
    K = SKATER_PRIOR_GAMES and prior = last season's shots/game (>= 10 games
    then) else this season's league mean for the F or D group. Players absent
    from this season's data keep their row at games_played 0 / shots_per_game 0.
    """
    season = _resolve_season(season)
    print(f"\nCollecting season player stats for {season}...")

    client = NHLAPIClient()
    skater_data = client.get_skater_stats(season)

    if not skater_data or "data" not in skater_data:
        print("  ❌ No skater data available")
        return

    rows = skater_data["data"]
    total = skater_data.get("total")
    if total is not None and len(rows) < total:
        print(f"  ⚠️  Got {len(rows)} of {total} skaters; stats are incomplete")

    prior_data = client.get_skater_stats(season - PRIOR_SEASON_STEP)
    prior_rate = {
        p["playerId"]: p.get("shots", 0) / p["gamesPlayed"]
        for p in ((prior_data or {}).get("data") or [])
        if (p.get("gamesPlayed") or 0) >= SKATER_PRIOR_GAMES
    }

    def group(row):
        return "D" if row.get("positionCode") == "D" else "F"

    league_shots, league_games = defaultdict(int), defaultdict(int)
    for row in rows:
        league_shots[group(row)] += row.get("shots", 0)
        league_games[group(row)] += row.get("gamesPlayed", 0)
    league_rate = {
        g: league_shots[g] / league_games[g] for g in league_games if league_games[g]
    }

    # Create team abbreviation to ID mapping
    team_abbrev_to_id = {abbrev: info["id"] for abbrev, info in NHL_TEAMS.items()}
    team_abbrev_to_name = {abbrev: info["name"] for abbrev, info in NHL_TEAMS.items()}

    players_updated = 0
    seen_ids = set()

    for player_stats in rows:
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

        seen_ids.add(player_id)

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

        prior = prior_rate.get(player_id, league_rate.get(group(player_stats), 0.0))
        player.shots_per_game = (player.shots + SKATER_PRIOR_GAMES * prior) / (
            player.games_played + SKATER_PRIOR_GAMES
        )

        player.last_updated = datetime.utcnow()
        players_updated += 1

    # Players not in this season's data must never look like current players
    for player in db_session.query(NHLPlayer).all():
        if player.player_id in seen_ids:
            continue
        player.games_played = 0
        player.goals = player.assists = player.points = player.shots = 0
        player.toi_per_game = 0.0
        player.shots_per_game = 0

    db_session.commit()
    print(f"  ✓ Updated {players_updated} players")


def collect_team_offensive_stats(season=None):
    """
    Collect detailed team offensive statistics (current-season regular season)
    Used for: team total goals predictions, over/under predictions
    """
    season = _resolve_season(season)
    print(f"\nCollecting team offensive stats for {season}...")

    current = _team_games(season)

    if not current:
        print("  ❌ No games found for season")
        return

    teams_updated = 0
    for team_id, rows in current.items():
        team = db_session.query(NHLTeamStats).filter_by(team_id=team_id).first()
        if not team:
            continue
        home = [r["gf"] for r in rows if r["home"]]
        away = [r["gf"] for r in rows if not r["home"]]
        # (no pred_nhl_team_stats columns yet; kept as plain attributes)
        team.home_goals_per_game = sum(home) / len(home) if home else None
        team.away_goals_per_game = sum(away) / len(away) if away else None

        shots = sum(r["sf"] for r in rows)
        if shots > 0:
            team.shooting_pct = sum(r["gf"] for r in rows) / shots

        teams_updated += 1

    db_session.commit()
    print(f"  ✓ Updated offensive stats for {teams_updated} teams")


def update_daily_stats(season=None):
    """
    Daily update function - brings ALL stats in line with the latest games.
    run_ingest and the 05:00 ET pipeline both land here, so both leave the
    tables in the same state.

    Includes:
    - New finished games (incremental), goalie actuals
    - Goalie, team and skater season rebuilds (current season, shrunk rates)
    - Team special teams (PP%, PK%), blocked shots, shot quality
    """
    season = _resolve_season(season)
    print("\n" + "=" * 80)
    print(f"📅 DAILY STATS UPDATE - Season {season}")
    print("=" * 80)

    collect_game_data(season=season)

    calculate_goalie_stats(season)
    calculate_team_stats(season)

    # Update special teams stats (PP%, PK%)
    update_special_teams_stats(season)

    # Update realtime stats (blocked shots)
    update_realtime_stats(season)

    # Update shot quality metrics (sample recent games)
    calculate_shot_quality_metrics(season, sample_games=30)

    # Player stats for shots/goals predictions
    collect_season_player_stats(season)

    # Team offensive trends for totals predictions
    collect_team_offensive_stats(season)

    print("\n" + "=" * 80)
    print("✅ Daily update complete!")
    print("   - Game, goalie, team and skater tables rebuilt for the current season")
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

        # After backfill, rebuild everything for the current season
        print("\n📊 Updating statistics for current season...")
        update_daily_stats(current_season)
    else:
        # Default mode: current season only
        print("\n💡 Tip: Use --backfill to load historical data from 2021-2025")
        print("   This will improve goalie vs-team history and shot quality metrics")
        print("\n💡 Tip: Use --daily-update to update team stats daily\n")

        update_daily_stats(current_season)

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
        update_daily_stats(season=season)
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
