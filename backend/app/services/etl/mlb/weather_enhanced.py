"""Enhanced Weather Model with Air Density and Dynamic Park Factors.

Combines temperature, humidity, altitude, barometric pressure, and wind
direction to compute physics-based adjustments to run scoring and HR rate.

Research basis:
- Each 1F increase raises HR rate by ~1% (Alan Nathan)
- 5 mph tailwind adds ~19 feet of carry
- 10% decrease in air density = ~4% more distance
- At Wrigley with wind blowing out >=10 mph, over has hit >60% since 2005
- Dynamic park factors using current year + previous year outperform multi-year averages

Formula: Expected_Runs_Adjustment = (T-72)*0.05 + wind_component + (altitude/1000)*0.15 + (29.92-P)*2.0

Technical Playbook §5 — Weather Coefficients.
"""

import sys
import os

import logging
import math

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# Stadium altitude in feet (above sea level)
STADIUM_ALTITUDE = {
    "Chase Field": 1082,
    "Truist Park": 1050,
    "Oriole Park at Camden Yards": 130,
    "Fenway Park": 20,
    "Wrigley Field": 595,
    "Guaranteed Rate Field": 595,
    "Great American Ball Park": 550,
    "Progressive Field": 650,
    "Coors Field": 5280,
    "Comerica Park": 600,
    "Minute Maid Park": 40,
    "Kauffman Stadium": 750,
    "Angel Stadium": 160,
    "Dodger Stadium": 515,
    "loanDepot park": 6,
    "American Family Field": 640,
    "Target Field": 830,
    "Citi Field": 10,
    "Yankee Stadium": 10,
    "Sutter Health Park": 30,
    "Oakland Coliseum": 5,
    "Citizens Bank Park": 20,
    "PNC Park": 730,
    "Petco Park": 15,
    "Oracle Park": 5,
    "T-Mobile Park": 5,
    "Busch Stadium": 455,
    "Tropicana Field": 25,
    "Globe Life Field": 545,
    "Rogers Centre": 250,
    "Nationals Park": 15,
}

# Stadium home plate orientation (degrees from north, 0=N, 90=E, 180=S, 270=W)
# Used to compute wind relative to home plate
STADIUM_HP_ORIENTATION = {
    "Chase Field": 0,
    "Truist Park": 225,
    "Oriole Park at Camden Yards": 210,
    "Fenway Park": 250,
    "Wrigley Field": 235,
    "Guaranteed Rate Field": 225,
    "Great American Ball Park": 210,
    "Progressive Field": 215,
    "Coors Field": 210,
    "Comerica Park": 220,
    "Minute Maid Park": 295,
    "Kauffman Stadium": 245,
    "Angel Stadium": 255,
    "Dodger Stadium": 220,
    "loanDepot park": 220,
    "American Family Field": 0,
    "Target Field": 220,
    "Citi Field": 225,
    "Yankee Stadium": 210,
    "Sutter Health Park": 225,
    "Oakland Coliseum": 195,
    "Citizens Bank Park": 225,
    "PNC Park": 270,
    "Petco Park": 270,
    "Oracle Park": 215,
    "T-Mobile Park": 315,
    "Busch Stadium": 230,
    "Tropicana Field": 0,
    "Globe Life Field": 0,
    "Rogers Centre": 0,
    "Nationals Park": 225,
}

# Domed/retractable roof stadiums (weather effects reduced)
DOMED_STADIUMS = {
    "Tropicana Field",
    "Globe Life Field",
    "loanDepot park",
    "Minute Maid Park",
    "American Family Field",
    "Rogers Centre",
    "Chase Field",
    "T-Mobile Park",
}

# Standard barometric pressure at sea level (inches Hg)
STANDARD_PRESSURE = 29.92


def compute_air_density_factor(
    temperature_f, humidity_pct, altitude_ft, pressure_inhg=None
):
    """Compute relative air density factor compared to standard conditions.

    Lower air density = less drag = more carry on batted balls.

    Returns:
        float: relative density (1.0 = standard, <1.0 = thinner air)
    """
    # Convert temperature to Celsius for density calculation
    temp_c = (temperature_f - 32) * 5.0 / 9.0
    temp_k = temp_c + 273.15

    # Estimate pressure if not provided (standard atmosphere lapse)
    if pressure_inhg is None:
        # Barometric formula: P = P0 * (1 - L*h/T0)^(g*M/(R*L))
        # L = 0.0065 K/m, T0 = 288.15 K, convert ft to m via 0.3048
        # Coefficient = L * 0.3048 / T0 = 0.0000068756 per foot
        pressure_inhg = STANDARD_PRESSURE * (1 - altitude_ft * 0.0000068756) ** 5.2553

    # Saturation vapor pressure (Magnus formula)
    e_sat = 6.1078 * 10 ** (7.5 * temp_c / (237.3 + temp_c))  # in hPa
    e_actual = e_sat * (humidity_pct / 100.0)

    # Convert pressure to hPa
    pressure_hpa = pressure_inhg * 33.8639

    # Dry air density: rho = P / (R_d * T)
    # Humid air: rho = (P - 0.378 * e) / (R_d * T)
    # R_d = 287.05 J/(kg*K)
    rho = (pressure_hpa * 100 - 0.378 * e_actual * 100) / (287.05 * temp_k)

    # Standard density at 72F, 50% humidity, sea level
    rho_standard = (STANDARD_PRESSURE * 33.8639 * 100 - 0.378 * 12.0 * 100) / (
        287.05 * 295.37
    )

    return round(rho / rho_standard, 4)


def compute_wind_component(wind_speed_mph, wind_direction_deg, venue_name):
    """Compute wind effect on batted ball carry.

    Positive value = wind helping offense (blowing out).
    Negative value = wind hurting offense (blowing in).

    A 5 mph tailwind adds ~19 feet of carry (Nathan).
    """
    if venue_name in DOMED_STADIUMS:
        return 0.0

    hp_orientation = STADIUM_HP_ORIENTATION.get(venue_name, 225)

    # Wind blowing from home plate toward center field = "blowing out"
    # HP orientation is where the batter faces
    outfield_direction = hp_orientation  # Direction batter faces (toward CF)

    # Relative angle: 0 = direct tailwind (blowing out), 180 = headwind (blowing in)
    relative_angle = abs(wind_direction_deg - outfield_direction)
    if relative_angle > 180:
        relative_angle = 360 - relative_angle

    # Cosine projection of wind onto outfield axis
    # cos(0) = 1.0 (full tailwind), cos(90) = 0 (crosswind), cos(180) = -1 (headwind)
    wind_cos = math.cos(math.radians(relative_angle))

    # 5 mph tailwind = +19 feet, ~3.8 ft per mph
    # Convert feet of carry to approximate run impact
    # ~10 feet of extra carry ≈ +0.15 runs per game (rough estimate)
    carry_effect = wind_speed_mph * wind_cos * 3.8
    run_impact = carry_effect * 0.015

    return round(run_impact, 3)


def compute_temperature_adjustment(temperature_f):
    """Compute temperature effect on run scoring.

    Each 1F above 72F adds ~0.05 runs. Below 72F subtracts.
    Research: 1.96% more HR per 1C, +2.53 runs/game at warmest vs coldest.
    """
    return round((temperature_f - 72.0) * 0.05, 3)


def compute_altitude_adjustment(venue_name):
    """Compute altitude effect on run scoring.

    Higher altitude = thinner air = more carry = more runs.
    ~0.15 runs per 1000 feet of elevation.
    """
    altitude = STADIUM_ALTITUDE.get(venue_name, 0)
    return round((altitude / 1000.0) * 0.15, 3)


def compute_weather_run_adjustment(
    temperature_f,
    wind_speed_mph,
    wind_direction_deg,
    humidity_pct,
    venue_name,
    pressure_inhg=None,
):
    """Compute total weather-based run adjustment.

    Combines temperature, wind, altitude, and air density effects.

    Returns:
        dict with:
            total_adjustment: float (expected runs above/below average)
            temperature_adj: float
            wind_adj: float
            altitude_adj: float
            air_density: float (relative to standard)
            is_domed: bool
    """
    if venue_name in DOMED_STADIUMS:
        return {
            "total_adjustment": 0.0,
            "temperature_adj": 0.0,
            "wind_adj": 0.0,
            "altitude_adj": 0.0,
            "air_density": 1.0,
            "is_domed": True,
        }

    temp_adj = compute_temperature_adjustment(temperature_f)
    wind_adj = compute_wind_component(wind_speed_mph, wind_direction_deg, venue_name)
    alt_adj = compute_altitude_adjustment(venue_name)

    altitude = STADIUM_ALTITUDE.get(venue_name, 0)
    air_density = compute_air_density_factor(
        temperature_f, humidity_pct, altitude, pressure_inhg
    )

    # Air density adjustment: 10% decrease = ~4% more distance = ~0.3 runs
    density_adj = (1.0 - air_density) * 3.0

    total = temp_adj + wind_adj + alt_adj + density_adj

    return {
        "total_adjustment": round(total, 3),
        "temperature_adj": temp_adj,
        "wind_adj": wind_adj,
        "altitude_adj": alt_adj,
        "density_adj": round(density_adj, 3),
        "air_density": air_density,
        "is_domed": False,
    }


def get_dynamic_park_factor(venue_name, base_factor, weather_adjustment):
    """Compute dynamic, weather-adjusted park factor.

    Combines the static park factor with game-day weather conditions.
    Research: BP found current year + previous year outperforms multi-year averages.

    Args:
        venue_name: Stadium name
        base_factor: Static park factor from park_factors.csv (e.g., 1.05)
        weather_adjustment: Total weather run adjustment from compute_weather_run_adjustment()

    Returns:
        float: Dynamic park factor for this game
    """
    # Convert weather adjustment to park factor scale
    # Average MLB game: ~9 runs. Weather adj of +0.5 runs = +5.6% scoring = 1.056 factor
    weather_factor = 1.0 + (weather_adjustment / 9.0)

    # Blend static and weather-dynamic factors
    dynamic = base_factor * weather_factor

    return round(dynamic, 4)
