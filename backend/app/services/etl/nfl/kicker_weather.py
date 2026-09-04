"""Map NFLWeather rows and kicker volume inputs for FG projections."""

from __future__ import annotations

from typing import Any, Mapping


def weather_dict_from_nfl_row(row: Any) -> dict[str, float] | None:
    """Extract temperature / wind_speed from a pred_nfl_weather row."""
    if row is None:
        return None
    temperature = getattr(row, "temperature", None)
    wind_speed = getattr(row, "wind_speed", None)
    if temperature is None and wind_speed is None:
        return None
    return {"temperature": temperature, "wind_speed": wind_speed}


def kicker_stat_inputs(kicker_data: Mapping[str, Any] | None) -> dict[str, Any]:
    """Career/form inputs for the statistical kicker path; league defaults if missing."""
    data = dict(kicker_data or {})

    career = data.get("career_fg_percentage")
    if career is None:
        career = data.get("fg_pct")
    if career is None:
        career = data.get("fg_percentage")
    if career is None:
        made = data.get("made")
        attempts = data.get("attempts")
        try:
            if made is not None and attempts not in (None, 0, 0.0):
                career = (float(made) / float(attempts)) * 100.0
        except (TypeError, ValueError, ZeroDivisionError):
            career = None
    if career is None:
        career = 82

    total_attempts = data.get("total_attempts")
    if total_attempts is None:
        total_attempts = data.get("fg_attempts")
    if total_attempts is None:
        total_attempts = data.get("attempts")
    if total_attempts is None:
        total_attempts = 35

    recent_form = data.get("recent_form")
    if recent_form is None:
        recent_form = 0.80

    return {
        "career_fg_percentage": career,
        "total_attempts": total_attempts,
        "recent_form": recent_form,
    }


def weather_make_multiplier(
    *,
    wind_speed: float | None,
    temperature: float | None,
    is_dome: bool,
) -> float:
    """Make-rate weather multiplier, clamped to [0.85, 1.05]. Domes are neutral."""
    if is_dome:
        return 1.0
    multiplier = 1.0
    if wind_speed is not None and float(wind_speed) > 18:
        multiplier *= 0.95
    if temperature is not None and float(temperature) < 32:
        multiplier *= 0.97
    return float(max(0.85, min(1.05, multiplier)))
