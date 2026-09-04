from pathlib import Path
from types import SimpleNamespace

from app.services.etl.nfl.kicker_weather import (
    kicker_stat_inputs,
    weather_dict_from_nfl_row,
    weather_make_multiplier,
)


def test_weather_dict_from_nfl_row():
    row = SimpleNamespace(
        temperature=41.0, wind_speed=22.0, venue_name="Highmark Stadium"
    )
    out = weather_dict_from_nfl_row(row)
    assert out == {"temperature": 41.0, "wind_speed": 22.0}


def test_kicker_stat_inputs_prefers_row_over_league_defaults():
    out = kicker_stat_inputs(
        {
            "career_fg_percentage": 91.2,
            "total_attempts": 88,
            "recent_form": 0.93,
        }
    )
    assert out["career_fg_percentage"] == 91.2
    assert out["total_attempts"] == 88
    assert out["recent_form"] == 0.93


def test_kicker_stat_inputs_defaults_when_missing():
    out = kicker_stat_inputs({})
    assert out["career_fg_percentage"] == 82
    assert out["total_attempts"] == 35
    assert out["recent_form"] == 0.80


def test_kicker_stat_inputs_maps_fg_pct_and_attempts():
    out = kicker_stat_inputs({"fg_pct": 88.0, "fg_attempts": 40})
    assert out["career_fg_percentage"] == 88.0
    assert out["total_attempts"] == 40
    assert out["recent_form"] == 0.80


def test_kicker_stat_inputs_maps_fg_percentage_and_attempts():
    out = kicker_stat_inputs({"fg_percentage": 85.5, "attempts": 22})
    assert out["career_fg_percentage"] == 85.5
    assert out["total_attempts"] == 22


def test_weather_make_multiplier_dome_neutral():
    assert (
        weather_make_multiplier(wind_speed=30.0, temperature=10.0, is_dome=True) == 1.0
    )


def test_weather_make_multiplier_wind_reduces():
    calm = weather_make_multiplier(wind_speed=5.0, temperature=60.0, is_dome=False)
    windy = weather_make_multiplier(wind_speed=22.0, temperature=60.0, is_dome=False)
    assert windy < calm
    assert 0.85 <= windy <= 1.05


def test_weather_make_multiplier_cold_reduces():
    mild = weather_make_multiplier(wind_speed=5.0, temperature=60.0, is_dome=False)
    cold = weather_make_multiplier(wind_speed=5.0, temperature=20.0, is_dome=False)
    assert cold < mild
    assert 0.85 <= cold <= 1.05


def test_kickers_module_does_not_import_weather_integration():
    kickers_path = (
        Path(__file__).resolve().parents[1] / "app/services/etl/nfl/kickers.py"
    )
    text = kickers_path.read_text()
    assert "weather_integration" not in text
