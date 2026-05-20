# Import enhanced statistical prediction system

try:
    from app.services.etl.nfl.statistical_kicker_prediction import (
        calculate_combined_score as enhanced_calculate_combined_score,
    )

    ENHANCED_PREDICTIONS_AVAILABLE = True
    print("✅ Enhanced nflverse-based predictions loaded")
except ImportError:
    ENHANCED_PREDICTIONS_AVAILABLE = False
    print("⚠️ Using legacy prediction system")


def calculate_combined_score(stats, upcoming_surface=None, upcoming_location=None):
    """
    Enhanced field goal prediction using nflverse historical data
    Falls back to legacy system if enhanced predictions unavailable
    """
    if ENHANCED_PREDICTIONS_AVAILABLE:
        try:
            # Use the new enhanced statistical prediction system
            return enhanced_calculate_combined_score(
                stats, upcoming_surface, upcoming_location
            )
        except Exception as e:
            print(f"Enhanced prediction failed: {e}, falling back to legacy")

    # Legacy prediction system (fallback)
    return calculate_combined_score_legacy(stats, upcoming_surface, upcoming_location)


def calculate_combined_score_legacy(
    stats, upcoming_surface=None, upcoming_location=None
):
    """Legacy prediction system - kept as fallback"""
    # Base weights for factors
    weights = {
        "Team Red Zone Efficiency": 0.20,
        "3rd Down Conversion Rate": 0.1,
        "Red Zone Touchdown Percentage": 0.10,
        "Red Zone Field Goal Percentage": 0.20,
        "Wind Speed": 0.05,
        "Temperature": 0.03,
        "Precipitation Probability": 0.05,
        "Career Surface Stats": 0.05,
        "Career Location Stats": 0.05,
        "Career Field Position Stats": 0.05,
    }

    # Adjust values dynamically based on whether they are above/below certain thresholds

    # Check Team Red Zone Efficiency (higher means fewer field goal attempts)
    red_zone_efficiency = stats.get("team_red_zone_efficiency", 0) or 0
    if red_zone_efficiency > 60:  # Assume 60% is average
        weights[
            "Team Red Zone Efficiency"
        ] *= 0.5  # Reduce the weight if it's above average

    # Check 3rd Down Conversion Rate (lower means more field goal attempts)
    third_down_conversion_rate = stats.get("third_down_conversion_rate", 0) or 0
    if third_down_conversion_rate < 40:  # Assume 40% is average
        weights[
            "3rd Down Conversion Rate"
        ] *= 1.5  # Increase weight if below average (more field goal attempts)

    # Red Zone Touchdown Percentage (high means fewer field goals)
    redzone_touchdown_pct = stats.get("redzone_touchdown_pct", 0) or 0
    if redzone_touchdown_pct > 50:  # Assume 50% is average
        weights[
            "Red Zone Touchdown Percentage"
        ] *= 0.7  # Reduce weight if above average (fewer field goal attempts)

    # Red Zone Field Goal Percentage (higher means more field goals)
    redzone_field_goal_pct = stats.get("redzone_field_goal_pct", 0) or 0
    if redzone_field_goal_pct > 80:  # Assume 80% is good
        weights[
            "Red Zone Field Goal Percentage"
        ] *= 1.2  # Boost if above average (more successful field goals)

    # Wind Speed (higher than 8 mph reduces success)
    wind_speed = stats.get("wind_speed", 0) or 0
    if wind_speed > 8:
        weights["Wind Speed"] *= 0.5  # Reduce weight if wind is high (negative impact)

    # Temperature (below 30°F reduces success)
    temperature = stats.get("temperature", 32) or 32
    if temperature < 30:
        weights[
            "Temperature"
        ] *= 1.5  # Increase weight if it's cold (more attempts, harder success)

    # Precipitation Probability (higher means worse field goal chances)
    precipitation_probability = stats.get("precipitation_probability", 0) or 0
    if precipitation_probability > 50:  # Assume 50% precipitation is significant
        weights[
            "Precipitation Probability"
        ] *= 0.5  # Reduce weight if high precipitation (lower success)

    # Boost the weight if playing on a surface or location the kicker has excelled at
    if upcoming_surface:
        surface_boost = get_surface_boost(
            stats.get("career_surface_stats", []), upcoming_surface
        )
        weights["Career Surface Stats"] += surface_boost

    if upcoming_location:
        location_boost = get_location_boost(
            stats.get("career_location_stats", []), upcoming_location
        )
        weights["Career Location Stats"] += location_boost

    # Normalize the stats based on these adjustments
    normalized_stats = {
        "Team Red Zone Efficiency": 1 - (red_zone_efficiency / 100),
        "3rd Down Conversion Rate": 1 - (third_down_conversion_rate / 100),
        "Red Zone Touchdown Percentage": 1 - (redzone_touchdown_pct / 100),
        "Red Zone Field Goal Percentage": redzone_field_goal_pct / 100,
        "Wind Speed": 1 if wind_speed > 8 else 0,
        "Temperature": 1 if temperature < 30 else 0,
        "Precipitation Probability": precipitation_probability / 100,
        "Career Surface Stats": extract_success_rate(
            stats.get("career_surface_stats", [])
        ),
        "Career Location Stats": extract_success_rate(
            stats.get("career_location_stats", [])
        ),
        "Career Field Position Stats": extract_success_rate(
            stats.get("career_field_position_stats", [])
        ),
    }

    # Calculate the combined score
    combined_score = sum(
        normalized_stats[stat] * weights[stat] for stat in normalized_stats
    )
    projected_field_goals = combined_score * 1.5  # Scaling factor

    return round(projected_field_goals, 2)


def get_surface_boost(career_surface_stats, upcoming_surface):
    """
    Check kicker's performance on the given surface (turf/grass) and return a boost if performance is above average.
    """
    for stat in career_surface_stats:
        if stat["displayName"].lower() == upcoming_surface.lower():
            success_rate = extract_success_rate([stat])
            if success_rate > 0.8:  # Assuming success rate > 80% is excellent
                return 0.05  # Apply a boost of 0.05 to the weight
    return 0


def get_location_boost(career_location_stats, upcoming_location):
    """
    Check kicker's performance in the given location (indoors/outdoors) and return a boost if performance is above average.
    """
    for stat in career_location_stats:
        if stat["displayName"].lower() == upcoming_location.lower():
            success_rate = extract_success_rate([stat])
            if success_rate > 0.8:  # Assuming success rate > 80% is excellent
                return 0.05  # Apply a boost of 0.05 to the weight
    return 0


def extract_success_rate(stat_list):
    """
    Extract the success rate from the career stats.
    Assumes the relevant stat is the highest percentage found in the 'stats' list.
    """
    if not stat_list:
        return 0

    for stat in stat_list:
        if "stats" in stat and isinstance(stat["stats"], list):
            for value in stat["stats"]:
                try:
                    percentage = float(value)
                    if 0 <= percentage <= 100:
                        return percentage / 100  # Normalize to [0, 1]
                except ValueError:
                    continue
    return 0
