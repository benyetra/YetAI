from app.services.etl.nfl._db import db_session
from datetime import datetime, timedelta
from typing import Dict, Optional
import requests

from app.models.predictions_models import Kickers, KickerPredictions
from app.services.etl.nfl.kicker_prediction import calculate_combined_score
from app.services.etl.nfl.nfl_common import get_current_nfl_week, get_nfl_season


# Dynamic season and week detection
season = get_nfl_season()
current_week = get_current_nfl_week(season)
regular_season = 2
pre_season = 1


# Ensure the tables are created if they don't exist
def get_team_schedule(team_id):
    """Get team schedule using proper NFL week calculation"""
    try:
        # Use the proper week calculation function
        current_week = get_current_nfl_week(season)
        current_season = get_nfl_season()

        # Get full season schedule and filter for current/upcoming games
        url = f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team_id}/schedule?season={current_season}&seasontype=2"
        response = requests.get(url)

        if response.status_code == 200:
            schedule_data = response.json()

            # Filter for upcoming games (current week and beyond)
            current_time = datetime.now()
            upcoming_events = []

            for event in schedule_data.get("events", []):
                try:
                    game_time = datetime.strptime(event["date"], "%Y-%m-%dT%H:%MZ")
                    # Include games from current week onwards
                    if (
                        game_time >= current_time
                        or event.get("week", {}).get("number", 0) >= current_week
                    ):
                        upcoming_events.append(event)
                except (ValueError, KeyError):
                    continue

            # Sort by date to get next games first
            upcoming_events.sort(key=lambda x: x["date"])

            # Return schedule data with filtered events
            schedule_data["events"] = upcoming_events
            return schedule_data
        else:
            print(
                f"Failed to fetch schedule for team {team_id}: {response.status_code}"
            )
            return None

    except Exception as e:
        print(f"Error getting schedule for team {team_id}: {e}")
        return None


def get_opponent_team_id(team_id):
    """Get opponent team ID for the next upcoming game"""
    schedule = get_team_schedule(team_id)
    if schedule and schedule.get("events"):
        # Get the next upcoming game (first in sorted list)
        next_game = schedule["events"][0]
        try:
            for competitor in next_game["competitions"][0]["competitors"]:
                if competitor["team"]["id"] != str(team_id):
                    return competitor["team"]["id"]
        except (KeyError, IndexError) as e:
            print(f"Error parsing game data for team {team_id}: {e}")
    return None


def get_nfl_teams():
    url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        teams = data["sports"][0]["leagues"][0]["teams"]
        team_info = []
        for team in teams:
            team_info.append(
                {"id": team["team"]["id"], "name": team["team"]["displayName"]}
            )
        return team_info
    else:
        print(f"Failed to fetch teams: {response.status_code}")
        return None


def get_team_roster(team_id):
    url = f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team_id}/roster"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        kickers = []
        for group in data["athletes"]:
            for player in group["items"]:
                if player["position"]["abbreviation"] == "PK":
                    kickers.append(
                        {
                            "id": player["id"],
                            "name": player["fullName"],
                            "team_id": team_id,
                        }
                    )
        return kickers
    else:
        print(f"Failed to fetch roster for team {team_id}: {response.status_code}")
        return None


def get_all_starting_kickers():
    teams = get_nfl_teams()
    all_kickers = []
    if teams:
        for team in teams:
            kickers = get_team_starting_kicker(team["id"], season)
            if kickers:
                all_kickers.append(kickers)
    return all_kickers


def get_team_starting_kicker(team_id, season):
    depthchart_url = f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/{season}/teams/{team_id}/depthcharts"
    response = requests.get(depthchart_url)
    if response.status_code != 200:
        print(
            f"Failed to fetch depth chart for team {team_id} in season {season}: {response.status_code}"
        )
        return None

    depthchart_data = response.json()

    # Iterate through the depth chart positions to find the Place Kicker (PK)
    for item in depthchart_data["items"]:
        positions = item.get("positions", {})
        if "pk" in positions:
            place_kicker_position = positions["pk"]
            if place_kicker_position["athletes"]:
                # The first athlete in the list should be the starter
                athlete_ref = place_kicker_position["athletes"][0]["athlete"]["$ref"]
                athlete_response = requests.get(athlete_ref)
                if athlete_response.status_code == 200:
                    athlete_data = athlete_response.json()
                    full_name = athlete_data.get("fullName", "Unknown")
                    player_id = athlete_data.get("id")
                    return {
                        "team_id": team_id,
                        "player_id": player_id,
                        "name": full_name,
                        "athlete_ref": athlete_ref,
                    }
                else:
                    print(
                        f"Failed to fetch athlete details from {athlete_ref}: {athlete_response.status_code}"
                    )
                    return None

    print(f"No starting kicker found for team {team_id}")
    return None


def get_kicker_career_stats(player_id):
    url = f"https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/{player_id}/splits"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        print(
            f"Failed to fetch career stats for player {player_id}: {response.status_code}"
        )
        return None


def get_kicker_stats(player_id):
    url = f"https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/{player_id}/splits"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        print(
            f"Failed to fetch player stats for player {player_id}: {response.status_code}"
        )
        return {}


stat_labels = {
    "fieldGoalsMade1_19-fieldGoalAttempts1_19": "Field Goals Made 1-19 yards",
    "fieldGoalsMade20_29-fieldGoalAttempts20_29": "Field Goals Made 20-29 yards",
    "fieldGoalsMade30_39-fieldGoalAttempts30_39": "Field Goals Made 30-39 yards",
    "fieldGoalsMade40_49-fieldGoalAttempts40_49": "Field Goals Made 40-49 yards",
    "fieldGoalsMade50-fieldGoalAttempts50": "Field Goals Made 50+ yards",
    "fieldGoalsMade-fieldGoalAttempts": "Total Field Goals Made-Attempts",
    "fieldGoalPct": "Field Goal Percentage",
    "longFieldGoalMade": "Longest Field Goal Made",
    "extraPointsMade-extraPointAttempts": "Extra Points Made-Attempts",
    "totalKickingPoints": "Total Kicking Points",
    # Add other mappings as needed
}


def get_kicker_game_stats(player_id, season_year):
    url = f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/{season_year}/athletes/{player_id}/eventlog"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        events = data.get("events", {}).get("items", [])
        formatted_events = []
        for event in events:
            event_id = event.get("event", {}).get("$ref", "").split("/")[-1]
            stats = event.get("statistics", {})
            formatted_events.append({"event_id": event_id, "stats": stats})
        return formatted_events
    else:
        print(
            f"Failed to fetch game stats for player {player_id} in season {season_year}: {response.status_code}"
        )
        return []


# League-average priors used when ESPN has no usable season team stats yet
# (common in offseason / Week 1 before games are played).
_TEAM_STAT_PRIORS = {
    "team_red_zone_efficiency": 60.0,
    "opponent_red_zone_efficiency": 60.0,
    "third_down_conversion_rate": 40.0,
    "redzone_touchdown_pct": 55.0,
    "redzone_field_goal_pct": 80.0,
}

# ESPN team statistics categories[10] efficiency indices used historically.
_EFFICIENCY_CATEGORY_IDX = 10
_RED_ZONE_EFFICIENCY_STAT_IDX = 10
_REDZONE_FG_PCT_STAT_IDX = 11
_REDZONE_TD_PCT_STAT_IDX = 13
_THIRD_DOWN_CONV_STAT_IDX = 15
_YARDS_ALLOWED_CATEGORY_IDX = 4
_YARDS_ALLOWED_STAT_IDX = 23


def _has_usable_team_stats(payload) -> bool:
    """True when ESPN payload has enough categories for efficiency lookups."""
    if not isinstance(payload, dict):
        return False
    categories = (payload.get("splits") or {}).get("categories")
    return isinstance(categories, list) and len(categories) > _EFFICIENCY_CATEGORY_IDX


def _as_python_float(value) -> Optional[float]:
    """Coerce numpy / pandas scalars to plain float for DB binds."""
    if value is None:
        return None
    try:
        if hasattr(value, "item"):
            value = value.item()
    except Exception:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sanitize_feature_importance(raw) -> Dict[str, float]:
    """Ensure feature_importance JSON is JSON/DB-safe (no numpy scalars)."""
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, float] = {}
    for key, value in raw.items():
        coerced = _as_python_float(value)
        if coerced is not None:
            out[str(key)] = coerced
    return out


def _stat_at(payload, category_idx: int, stat_idx: int, default: float = 0.0) -> float:
    """Safely read ESPN splits.categories[i].stats[j].value."""
    try:
        categories = payload["splits"]["categories"]
        stats = categories[category_idx].get("stats") or []
        return float(stats[stat_idx].get("value", default))
    except (IndexError, KeyError, TypeError, ValueError, AttributeError):
        return float(default)


def _fetch_team_statistics_once(team_id, season_year, season_type=2):
    url = (
        "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/"
        f"seasons/{season_year}/types/{season_type}/teams/{team_id}/statistics"
    )
    try:
        response = requests.get(url, timeout=30)
    except requests.RequestException as exc:
        print(f"Failed to fetch team stats for team {team_id}: {exc}")
        return None

    if response.status_code != 200:
        print(f"Failed to fetch team stats for team {team_id}: {response.status_code}")
        return None

    try:
        payload = response.json()
    except ValueError as exc:
        print(f"Invalid team stats JSON for team {team_id}: {exc}")
        return None

    if not _has_usable_team_stats(payload):
        print(
            f"Team stats payload incomplete for team {team_id} "
            f"(season {season_year})"
        )
        return None
    return payload


def get_team_statistics(
    team_id, season_year=None, season_type=2, *, fallback_prior_season: bool = True
):
    """Fetch ESPN team statistics; fall back to prior season when current is empty.

    Returns None when no usable payload is available (never a stub with empty
    categories — those previously caused IndexError on categories[10]).
    """
    season_year = season_year or get_nfl_season()
    payload = _fetch_team_statistics_once(team_id, season_year, season_type)
    if payload is not None:
        return payload

    if fallback_prior_season and season_year:
        prior_season = int(season_year) - 1
        print(
            f"Falling back to {prior_season} team stats for team {team_id} "
            f"(no usable {season_year} data)"
        )
        return _fetch_team_statistics_once(team_id, prior_season, season_type)
    return None


def get_3rd_down_conversion_rate(team_id):
    stats = get_team_statistics(team_id)
    if not stats:
        return {
            "third_down_conversion_rate": _TEAM_STAT_PRIORS[
                "third_down_conversion_rate"
            ],
            "redzone_touchdown_pct": _TEAM_STAT_PRIORS["redzone_touchdown_pct"],
            "redzone_field_goal_pct": _TEAM_STAT_PRIORS["redzone_field_goal_pct"],
        }

    return {
        "third_down_conversion_rate": _stat_at(
            stats,
            _EFFICIENCY_CATEGORY_IDX,
            _THIRD_DOWN_CONV_STAT_IDX,
            _TEAM_STAT_PRIORS["third_down_conversion_rate"],
        ),
        "redzone_touchdown_pct": _stat_at(
            stats,
            _EFFICIENCY_CATEGORY_IDX,
            _REDZONE_TD_PCT_STAT_IDX,
            _TEAM_STAT_PRIORS["redzone_touchdown_pct"],
        ),
        "redzone_field_goal_pct": _stat_at(
            stats,
            _EFFICIENCY_CATEGORY_IDX,
            _REDZONE_FG_PCT_STAT_IDX,
            _TEAM_STAT_PRIORS["redzone_field_goal_pct"],
        ),
    }


def get_opponent_yards_allowed(team_id):
    stats = get_team_statistics(team_id)
    if not stats:
        return 0
    return _stat_at(
        stats, _YARDS_ALLOWED_CATEGORY_IDX, _YARDS_ALLOWED_STAT_IDX, default=0
    )


def process_kicker_data(kicker, team_name, opponent_name, game_time, venue_name):
    team_stats = get_team_statistics(kicker["team_id"], season, 2)
    if not team_stats:
        print(
            f"No usable ESPN team stats for team {kicker['team_id']}; "
            "using league-average priors"
        )

    kicker_stats = get_kicker_stats(kicker["player_id"])
    if not kicker_stats:
        print(f"Failed to fetch valid kicker stats for player {kicker['player_id']}")
        return

    # Extract relevant career stats and structure them
    career_stats = kicker_stats.get("splitCategories", [])

    career_surface_stats = next(
        (
            category.get("splits", [])
            for category in career_stats
            if category.get("displayName") == "Surface"
        ),
        [],
    )
    career_location_stats = next(
        (
            category.get("splits", [])
            for category in career_stats
            if category.get("displayName") == "Location"
        ),
        [],
    )
    career_field_position_stats = next(
        (
            category.get("splits", [])
            for category in career_stats
            if category.get("displayName") == "Field Position"
        ),
        [],
    )

    # Game stats for the kicker
    game_stats = get_kicker_game_stats(kicker["player_id"], season)
    if game_stats is None:
        game_stats = []

    # Get opponent information
    opponent_team_id = get_opponent_team_id(kicker["team_id"])
    if not opponent_team_id:
        print(f"Failed to fetch opponent team ID for team {kicker['team_id']}")
        return

    opponent_team_stats = get_team_statistics(opponent_team_id, season, 2)
    if not opponent_team_stats:
        print(
            f"No usable ESPN opponent team stats for team {opponent_team_id}; "
            "using league-average priors"
        )

    # Additional stats for the kicker
    conversion_rates = get_3rd_down_conversion_rate(kicker["team_id"])

    # Organize the data in a more detailed structure
    kicker_data = {
        "player_id": kicker["player_id"],
        "name": kicker["name"],
        "team_id": kicker["team_id"],
        "team_name": team_name,
        "venue_name": venue_name,
        "opponent_name": opponent_name,
        "game_time": game_time,
        "team_red_zone_efficiency": (
            _stat_at(
                team_stats,
                _EFFICIENCY_CATEGORY_IDX,
                _RED_ZONE_EFFICIENCY_STAT_IDX,
                _TEAM_STAT_PRIORS["team_red_zone_efficiency"],
            )
            if team_stats
            else _TEAM_STAT_PRIORS["team_red_zone_efficiency"]
        ),
        "opponent_red_zone_efficiency": (
            _stat_at(
                opponent_team_stats,
                _EFFICIENCY_CATEGORY_IDX,
                _RED_ZONE_EFFICIENCY_STAT_IDX,
                _TEAM_STAT_PRIORS["opponent_red_zone_efficiency"],
            )
            if opponent_team_stats
            else _TEAM_STAT_PRIORS["opponent_red_zone_efficiency"]
        ),
        "third_down_conversion_rate": conversion_rates["third_down_conversion_rate"],
        "redzone_touchdown_pct": conversion_rates["redzone_touchdown_pct"],
        "redzone_field_goal_pct": conversion_rates["redzone_field_goal_pct"],
        "career_surface_stats": career_surface_stats,
        "career_location_stats": career_location_stats,
        "career_field_position_stats": career_field_position_stats,
        "game_stats": game_stats,
    }

    # Defaults so ImportError / missing weather never leaves unbound locals
    weather_data = None
    weather_info = {}
    venue_type = "dome" if "dome" in (venue_name or "").lower() else "outdoor"
    surface_type = "turf" if "turf" in (venue_name or "").lower() else "grass"

    # Enhanced prediction with weather and game context
    try:
        from app.services.etl.nfl.statistical_kicker_prediction import (
            calculate_enhanced_statistical_score,
        )

        # Format data for enhanced prediction system (more realistic defaults)
        enhanced_kicker_data = {
            "career_fg_percentage": 82,  # More realistic NFL average
            "total_attempts": 35,  # Average experience level
            "recent_form": 0.80,  # Average recent performance
        }

        enhanced_team_data = {
            "team_red_zone_efficiency": kicker_data["team_red_zone_efficiency"],
            "third_down_conversion_rate": kicker_data["third_down_conversion_rate"],
            "venue_type": venue_type,
        }

        # Get live weather data for the venue
        try:
            from weather_integration import (
                get_live_weather_for_venue,
                get_venue_type,
                get_surface_type,
            )

            weather_info = get_live_weather_for_venue(venue_name, game_time)
            venue_type = get_venue_type(venue_name)
            surface_type = get_surface_type(venue_name)

            weather_data = {
                "temperature": weather_info["temperature"],
                "wind_speed": weather_info["wind_speed"],
            }

            print(
                f"🌡️ Weather for {venue_name}: {weather_info['temperature']}°F, {weather_info['wind_speed']}mph wind ({weather_info['source']})"
            )

        except ImportError:
            print("⚠️ Weather integration not available")
            weather_data = None

        # Update team data with venue info
        enhanced_team_data["venue_type"] = venue_type
        enhanced_team_data["surface_type"] = surface_type

        # Game context
        game_context = {
            "upcoming_surface": surface_type,
            "upcoming_location": "indoors" if venue_type == "dome" else "outdoors",
        }

        # Use enhanced statistical prediction
        projected_field_goals = calculate_enhanced_statistical_score(
            enhanced_kicker_data, enhanced_team_data, weather_data, game_context
        )

        try:
            from app.services.etl.nfl.ml_kicker_ensemble import (
                blend_field_goal_projection,
            )

            projected_field_goals, ml_meta = blend_field_goal_projection(
                projected_field_goals,
                enhanced_kicker_data,
                enhanced_team_data,
                weather_data,
                game_context,
            )
            if ml_meta.get("ml_used"):
                print(
                    f"🤖 ML blend for {kicker['name']}: {ml_meta.get('statistical_fgs')} → "
                    f"{projected_field_goals} (p={ml_meta.get('ml_success_probability')})"
                )
        except Exception as ml_exc:
            print(f"⚠️ ML kicker blend skipped for {kicker['name']}: {ml_exc}")

        print(f"✅ Enhanced prediction for {kicker['name']}: {projected_field_goals}")

    except ImportError:
        print("⚠️ Enhanced predictions not available, using legacy system")
        # Fallback to original calculation
        projected_field_goals = calculate_combined_score(kicker_data)

    kicker_data["projected_field_goals"] = projected_field_goals

    # Add weather and venue data to kicker_data for database storage
    if weather_data:
        kicker_data["temperature"] = weather_data.get("temperature")
        kicker_data["wind_speed"] = weather_data.get("wind_speed")
        kicker_data["weather_conditions"] = weather_info.get("conditions", "unknown")
    kicker_data["venue_type"] = venue_type
    kicker_data["surface_type"] = surface_type

    # Save the structured kicker data
    save_kicker_data(kicker_data)


def save_kicker_data(kicker_data):
    """
    Save kicker predictions to both current Kickers table and historical KickerPredictions table
    """
    game_date = (
        kicker_data["game_time"].date()
        if isinstance(kicker_data["game_time"], datetime)
        else kicker_data["game_time"]
    )

    # Coerce numeric fields up front so SQLAlchemy never binds numpy scalars
    # (psycopg2 otherwise literalizes np.float64 as "np.float64(...)" → schema "np").
    team_rz = _as_python_float(kicker_data.get("team_red_zone_efficiency", 0)) or 0.0
    opp_rz = _as_python_float(kicker_data.get("opponent_red_zone_efficiency", 0)) or 0.0
    third_down = (
        _as_python_float(kicker_data.get("third_down_conversion_rate", 0)) or 0.0
    )
    rz_td = _as_python_float(kicker_data.get("redzone_touchdown_pct", 0)) or 0.0
    rz_fg = _as_python_float(kicker_data.get("redzone_field_goal_pct", 0)) or 0.0
    projected_fg = _as_python_float(kicker_data.get("projected_field_goals", 0)) or 0.0
    temperature = _as_python_float(kicker_data.get("temperature"))
    wind_speed = _as_python_float(kicker_data.get("wind_speed"))

    # 1. Save to current Kickers table (for current week display)
    kicker = (
        db_session.query(Kickers)
        .filter_by(player_id=int(kicker_data["player_id"]))
        .first()
    )
    if not kicker:
        kicker = Kickers(
            player_id=int(kicker_data["player_id"]),
            name=kicker_data["name"],
            team_id=kicker_data["team_id"],
            team_name=kicker_data["team_name"],
            venue_name=kicker_data["venue_name"],
            opponent_team_name=kicker_data["opponent_name"],
            game_time=kicker_data["game_time"],
            team_red_zone_efficiency=team_rz,
            opponent_red_zone_efficiency=opp_rz,
            third_down_conversion_rate=third_down,
            redzone_touchdown_pct=rz_td,
            redzone_field_goal_pct=rz_fg,
            career_surface_stats=kicker_data.get("career_surface_stats", []),
            career_location_stats=kicker_data.get("career_location_stats", []),
            career_field_position_stats=kicker_data.get(
                "career_field_position_stats", []
            ),
            game_stats=kicker_data.get("game_stats", []),
            projected_field_goals=projected_fg,
            # Weather and venue information
            temperature=temperature,
            wind_speed=wind_speed,
            weather_conditions=kicker_data.get("weather_conditions"),
            venue_type=kicker_data.get("venue_type"),
            surface_type=kicker_data.get("surface_type"),
        )
        db_session.add(kicker)
    else:
        # Update current record
        kicker.team_red_zone_efficiency = team_rz
        kicker.opponent_red_zone_efficiency = opp_rz
        kicker.third_down_conversion_rate = third_down
        kicker.redzone_touchdown_pct = rz_td
        kicker.redzone_field_goal_pct = rz_fg
        kicker.career_surface_stats = kicker_data.get("career_surface_stats", [])
        kicker.career_location_stats = kicker_data.get("career_location_stats", [])
        kicker.career_field_position_stats = kicker_data.get(
            "career_field_position_stats", []
        )
        kicker.game_stats = kicker_data.get("game_stats", [])
        kicker.projected_field_goals = projected_fg
        kicker.game_time = kicker_data["game_time"]
        # Update weather and venue information
        kicker.temperature = temperature
        kicker.wind_speed = wind_speed
        kicker.weather_conditions = kicker_data.get("weather_conditions")
        kicker.venue_type = kicker_data.get("venue_type")
        kicker.surface_type = kicker_data.get("surface_type")

    # 2. Save to historical KickerPredictions table (ALWAYS create new record)
    # Check if prediction already exists for this player/date to avoid duplicates
    existing_prediction = (
        db_session.query(KickerPredictions)
        .filter_by(kicker_player_id=str(kicker_data["player_id"]), game_date=game_date)
        .first()
    )

    saved_historical = False
    predicted_fg_made = projected_fg
    if not existing_prediction:
        # Calculate distance-specific probabilities (placeholder logic - enhance as needed)
        predicted_fg_attempts = float(max(1.5, predicted_fg_made * 1.2))
        predicted_success_rate = float(
            min(
                0.95,
                (
                    predicted_fg_made / predicted_fg_attempts
                    if predicted_fg_attempts > 0
                    else 0.85
                ),
            )
        )

        wind_for_impact = wind_speed if wind_speed is not None else 0.0
        temp_for_impact = temperature if temperature is not None else 70.0
        feature_importance = _sanitize_feature_importance(
            {
                "team_red_zone_efficiency": team_rz,
                "weather_impact": (
                    wind_for_impact * -0.1 + (temp_for_impact - 70.0) * -0.02
                ),
                "venue_type": 0.1 if kicker_data.get("venue_type") == "dome" else 0.0,
                "surface_type": (
                    0.05 if kicker_data.get("surface_type") == "turf" else 0.0
                ),
            }
        )

        # Create instance with required parameters only (due to custom __init__)
        historical_prediction = KickerPredictions(
            kicker_player_id=str(kicker_data["player_id"]),
            kicker_player_name=kicker_data["name"],
            team_id=kicker_data["team_id"],
            team_name=kicker_data["team_name"],
            venue_name=kicker_data["venue_name"],
            opponent_team_name=kicker_data["opponent_name"],
            game_date=kicker_data["game_time"],
            predicted_fg_attempts=predicted_fg_attempts,
            predicted_fg_made=float(predicted_fg_made),
            predicted_success_rate=predicted_success_rate,
        )

        # Note: KickerPredictions model uses game_date for temporal tracking instead of season/week

        # Set additional attributes manually
        historical_prediction.short_distance_prob = float(
            min(0.95, predicted_success_rate + 0.1)
        )  # <30 yards
        historical_prediction.medium_distance_prob = float(
            predicted_success_rate
        )  # 30-49 yards
        historical_prediction.long_distance_prob = float(
            max(0.6, predicted_success_rate - 0.2)
        )  # 50+ yards
        historical_prediction.model_confidence = 0.75  # Placeholder confidence score
        historical_prediction.feature_importance = feature_importance
        historical_prediction.temperature = temperature
        historical_prediction.wind_speed = wind_speed
        historical_prediction.roof_type = kicker_data.get("venue_type")
        historical_prediction.surface_type = kicker_data.get("surface_type")

        db_session.add(historical_prediction)
        saved_historical = True
    else:
        print(
            f"⚠️ Prediction already exists for {kicker_data['name']} on {game_date}, skipping historical save"
        )

    try:
        db_session.commit()
        if saved_historical:
            print(
                f"📊 Saved historical prediction for {kicker_data['name']} on {game_date}: {predicted_fg_made} FGs"
            )
        print(f"✅ Successfully saved kicker data for {kicker_data['name']}")
    except Exception as e:
        db_session.rollback()
        print(f"❌ Error saving kicker data for {kicker_data['name']}: {e}")


def get_all_kicker_data():
    kickers = get_all_starting_kickers()
    kicker_data = []
    for kicker in kickers:
        try:
            processed_data = process_kicker_data(kicker)
            if processed_data:
                kicker_data.append(processed_data)
        except Exception as e:
            print(f"Error processing kicker {kicker['name']}: {e}")
    return kicker_data


def _run_kickers_core():
    print("🏈 Starting kicker prediction processing...")

    # Get all starting kickers
    kickers = get_all_starting_kickers()

    if not kickers:
        print("❌ No kickers found")
    else:
        print(f"📊 Processing {len(kickers)} kickers...")

        for i, kicker in enumerate(kickers, 1):
            if kicker:  # Make sure kicker data exists
                print(
                    f"\n[{i}/{len(kickers)}] Processing {kicker.get('name', 'Unknown')}..."
                )

                try:
                    # Get basic team info for context
                    teams = get_nfl_teams()
                    team_info = next(
                        (t for t in teams if t["id"] == kicker["team_id"]),
                        {"name": "Unknown Team"},
                    )

                    # Get game details
                    schedule = get_team_schedule(kicker["team_id"])
                    if (
                        schedule
                        and "events" in schedule
                        and len(schedule["events"]) > 0
                    ):
                        next_game = schedule["events"][0]
                        game_time = datetime.now() + timedelta(
                            days=1
                        )  # Default to tomorrow
                        venue_name = "Stadium"  # Default venue
                        opponent_name = "Opponent"  # Default opponent

                        # Extract game details if available
                        try:
                            competition = next_game["competitions"][0]
                            venue_name = competition.get("venue", {}).get(
                                "fullName", "Stadium"
                            )

                            # Find opponent
                            for competitor in competition["competitors"]:
                                if competitor["team"]["id"] != str(kicker["team_id"]):
                                    opponent_name = competitor["team"]["displayName"]
                                    break
                        except (KeyError, IndexError):
                            pass

                        # Process the kicker data
                        process_kicker_data(
                            kicker,
                            team_info["name"],
                            opponent_name,
                            game_time,
                            venue_name,
                        )
                    else:
                        print(f"⚠️ No schedule found for {kicker.get('name')}")

                except Exception as e:
                    print(f"❌ Error processing {kicker.get('name', 'Unknown')}: {e}")

        print(f"\n✅ Completed processing all kickers!")


def run() -> dict:
    from app.services.etl.nfl._db import close_session, init_session

    init_session()
    try:
        _run_kickers_core()
        return {"status": "ok", "task": "nfl_kickers"}
    finally:
        close_session()
