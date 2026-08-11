"""ESPN team-stats hardening for NFL kicker predictions (404 / empty payload)."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.services.etl.nfl import kickers


def _usable_payload(*, rz_eff=61.5, third_down=41.0, rz_td=54.0, rz_fg=82.0):
    """Minimal ESPN-shaped payload with enough categories for index lookups."""
    categories = [{"stats": []} for _ in range(11)]
    efficiency_stats = [{"value": 0} for _ in range(16)]
    efficiency_stats[10] = {"value": rz_eff}
    efficiency_stats[11] = {"value": rz_fg}
    efficiency_stats[13] = {"value": rz_td}
    efficiency_stats[15] = {"value": third_down}
    categories[10] = {"stats": efficiency_stats}
    return {"splits": {"categories": categories}}


def test_has_usable_team_stats_rejects_stub_and_short_lists():
    assert kickers._has_usable_team_stats(None) is False
    assert kickers._has_usable_team_stats({"splits": {"categories": [{}]}}) is False
    assert kickers._has_usable_team_stats({"splits": {"categories": []}}) is False
    assert kickers._has_usable_team_stats(_usable_payload()) is True


def test_stat_at_safe_on_missing_indexes():
    assert (
        kickers._stat_at({"splits": {"categories": [{}]}}, 10, 10, default=60) == 60.0
    )
    assert kickers._stat_at(_usable_payload(rz_eff=72), 10, 10) == 72.0


def test_get_team_statistics_404_returns_none_without_fallback(monkeypatch):
    monkeypatch.setattr(kickers, "get_nfl_season", lambda: 2026)

    def fake_get(url, timeout=30):
        m = MagicMock()
        m.status_code = 404
        return m

    with patch("app.services.etl.nfl.kickers.requests.get", side_effect=fake_get):
        assert (
            kickers.get_team_statistics(
                12, season_year=2026, fallback_prior_season=False
            )
            is None
        )


def test_get_team_statistics_falls_back_to_prior_season_on_404(monkeypatch):
    monkeypatch.setattr(kickers, "get_nfl_season", lambda: 2026)
    calls = []

    def fake_get(url, timeout=30):
        calls.append(url)
        m = MagicMock()
        if "/seasons/2026/" in url:
            m.status_code = 404
            return m
        m.status_code = 200
        m.json.return_value = _usable_payload(rz_eff=66)
        return m

    with patch("app.services.etl.nfl.kickers.requests.get", side_effect=fake_get):
        payload = kickers.get_team_statistics(12, season_year=2026)

    assert payload is not None
    assert kickers._stat_at(payload, 10, 10) == 66.0
    assert any("/seasons/2026/" in u for u in calls)
    assert any("/seasons/2025/" in u for u in calls)


def test_get_team_statistics_incomplete_200_falls_back(monkeypatch):
    monkeypatch.setattr(kickers, "get_nfl_season", lambda: 2026)

    def fake_get(url, timeout=30):
        m = MagicMock()
        m.status_code = 200
        if "/seasons/2026/" in url:
            # Legacy stub shape that previously caused IndexError
            m.json.return_value = {"splits": {"categories": [{}]}}
        else:
            m.json.return_value = _usable_payload()
        return m

    with patch("app.services.etl.nfl.kickers.requests.get", side_effect=fake_get):
        payload = kickers.get_team_statistics(7, season_year=2026)
    assert payload is not None
    assert kickers._has_usable_team_stats(payload)


def test_get_3rd_down_conversion_rate_uses_priors_when_no_stats(monkeypatch):
    monkeypatch.setattr(kickers, "get_team_statistics", lambda *a, **k: None)
    rates = kickers.get_3rd_down_conversion_rate(1)
    assert (
        rates["third_down_conversion_rate"]
        == kickers._TEAM_STAT_PRIORS["third_down_conversion_rate"]
    )
    assert (
        rates["redzone_touchdown_pct"]
        == kickers._TEAM_STAT_PRIORS["redzone_touchdown_pct"]
    )
    assert (
        rates["redzone_field_goal_pct"]
        == kickers._TEAM_STAT_PRIORS["redzone_field_goal_pct"]
    )


def test_process_kicker_data_survives_missing_team_stats(monkeypatch):
    """Regression: ESPN 404 stub used to raise list index out of range."""
    saved = {}

    monkeypatch.setattr(kickers, "get_team_statistics", lambda *a, **k: None)
    monkeypatch.setattr(
        kickers,
        "get_kicker_stats",
        lambda *_: {"splitCategories": []},
    )
    monkeypatch.setattr(kickers, "get_kicker_game_stats", lambda *a, **k: [])
    monkeypatch.setattr(kickers, "get_opponent_team_id", lambda *_: "22")
    monkeypatch.setattr(
        kickers,
        "get_3rd_down_conversion_rate",
        lambda *_: {
            "third_down_conversion_rate": 40.0,
            "redzone_touchdown_pct": 55.0,
            "redzone_field_goal_pct": 80.0,
        },
    )
    monkeypatch.setattr(kickers, "save_kicker_data", lambda data: saved.update(data))
    monkeypatch.setattr(kickers, "calculate_combined_score", lambda *_a, **_k: 1.7)

    kickers.process_kicker_data(
        {"player_id": "123", "name": "Test Kicker", "team_id": "12"},
        "Team A",
        "Team B",
        datetime(2026, 9, 10, 17, 0, 0),
        "Hard Rock Stadium",
    )

    assert saved["name"] == "Test Kicker"
    assert (
        saved["team_red_zone_efficiency"]
        == kickers._TEAM_STAT_PRIORS["team_red_zone_efficiency"]
    )
    assert (
        saved["opponent_red_zone_efficiency"]
        == kickers._TEAM_STAT_PRIORS["opponent_red_zone_efficiency"]
    )
    assert "projected_field_goals" in saved


def test_as_python_float_coerces_numpy_scalars():
    np = pytest.importorskip("numpy")
    assert kickers._as_python_float(None) is None
    assert kickers._as_python_float(np.float64(1.75)) == 1.75
    assert type(kickers._as_python_float(np.float64(1.75))) is float
    assert kickers._as_python_float("bad") is None
    assert kickers._sanitize_feature_importance(
        {"a": np.float64(0.3), "b": "x", "c": 1}
    ) == {"a": 0.3, "c": 1.0}


def test_save_kicker_data_binds_plain_python_floats(monkeypatch):
    """Regression: np.float64 in ORM fields made psycopg2 emit schema \"np\"."""
    np = pytest.importorskip("numpy")

    added = []
    mock_session = MagicMock()
    mock_session.query.return_value.filter_by.return_value.first.return_value = None
    mock_session.add.side_effect = lambda obj: added.append(obj)
    monkeypatch.setattr(kickers, "db_session", mock_session)

    kickers.save_kicker_data(
        {
            "player_id": "42",
            "name": "Justin Tucker",
            "team_id": 33,
            "team_name": "Ravens",
            "venue_name": "M&T Bank Stadium",
            "opponent_name": "Chiefs",
            "game_time": datetime(2026, 9, 10, 20, 15, 0),
            "team_red_zone_efficiency": np.float64(61.5),
            "opponent_red_zone_efficiency": np.float64(55.0),
            "third_down_conversion_rate": np.float64(40.2),
            "redzone_touchdown_pct": np.float64(54.0),
            "redzone_field_goal_pct": np.float64(82.0),
            "projected_field_goals": np.float64(1.8),
            "temperature": np.float64(68.0),
            "wind_speed": np.float64(12.0),
            "weather_conditions": "Clear",
            "venue_type": "outdoor",
            "surface_type": "grass",
            "career_surface_stats": [],
            "career_location_stats": [],
            "career_field_position_stats": [],
            "game_stats": [],
        }
    )

    assert mock_session.commit.called
    assert len(added) == 2
    historical = next(o for o in added if o.__class__.__name__ == "KickerPredictions")
    current = next(o for o in added if o.__class__.__name__ == "Kickers")

    for attr in (
        "predicted_fg_made",
        "predicted_fg_attempts",
        "predicted_success_rate",
        "short_distance_prob",
        "medium_distance_prob",
        "long_distance_prob",
        "temperature",
        "wind_speed",
    ):
        value = getattr(historical, attr)
        assert type(value) is float, f"{attr} is {type(value)}"
        assert "np." not in repr(value)

    assert type(current.projected_field_goals) is float
    assert "np." not in repr(current.projected_field_goals)
    for key, value in historical.feature_importance.items():
        assert type(value) is float, key
        assert "np." not in repr(value)
