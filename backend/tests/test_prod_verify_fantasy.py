"""Unit tests for prod_verify_fantasy threshold helpers (no live DB)."""

import pytest

from scripts.prod_verify_fantasy import (
    evaluate_db_health,
    format_mapping_summary,
    min_analytics_rows_for_season,
)


@pytest.mark.parametrize(
    ("season", "expected"),
    [
        (2023, 1),
        (2024, 1000),
        (2025, 1000),
    ],
)
def test_min_analytics_rows_for_season(season, expected):
    assert min_analytics_rows_for_season(season) == expected


def test_format_mapping_summary():
    summary = format_mapping_summary(
        {
            "season": 2025,
            "player_analytics_rows": 1547,
            "fantasy_players_mapped": 2100,
            "skip_rate_pct": 89.2,
        }
    )
    assert "season=2025" in summary
    assert "player_analytics_rows=1547" in summary
    assert "fantasy_players_mapped=2100" in summary
    assert "skip_rate_pct=89.2" in summary


def test_evaluate_db_health_ok_with_warnings():
    result = evaluate_db_health(
        {
            "season": 2025,
            "player_analytics_rows": 500,
            "fantasy_players_mapped": 800,
            "skip_rate_pct": 90.0,
        },
        season=2025,
        min_mapped=1000,
    )
    assert result["ok"] is True
    assert not result["failures"]
    assert len(result["warnings"]) == 2
    assert "player_analytics_rows 500 < 1000" in result["warnings"][0]
    assert "fantasy_players_mapped 800 < 1000" in result["warnings"][1]


def test_evaluate_db_health_critical_when_analytics_empty():
    result = evaluate_db_health(
        {
            "season": 2025,
            "player_analytics_rows": 0,
            "fantasy_players_mapped": 1500,
            "skip_rate_pct": 90.0,
        },
        season=2025,
        min_mapped=1000,
    )
    assert result["ok"] is False
    assert result["failures"] == ["player_analytics empty for season 2025"]
    assert result["warnings"] == []


def test_evaluate_db_health_healthy_no_warnings():
    result = evaluate_db_health(
        {
            "season": 2025,
            "player_analytics_rows": 1500,
            "fantasy_players_mapped": 1200,
            "skip_rate_pct": 88.0,
        },
        season=2025,
        min_mapped=1000,
    )
    assert result["ok"] is True
    assert result["failures"] == []
    assert result["warnings"] == []


def test_evaluate_db_health_respects_custom_threshold():
    result = evaluate_db_health(
        {
            "season": 2025,
            "player_analytics_rows": 50,
            "fantasy_players_mapped": 1200,
            "skip_rate_pct": 90.0,
        },
        season=2025,
        min_mapped=1000,
        min_analytics_rows=100,
    )
    assert result["ok"] is True
    assert result["warnings"] == [
        "player_analytics_rows 50 < 100 (expected for season 2025)"
    ]
