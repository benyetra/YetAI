"""Unit tests for MLB game pick grading helpers."""

from app.services.mlb_game_picks import (
    enrich_game_projection_row,
    grade_moneyline,
    grade_spread,
    grade_total,
    spread_recommendation,
)


def test_spread_recommendation_home_when_model_beats_market():
    assert spread_recommendation(2.0, -1.5) == "HOME"


def test_spread_recommendation_away_when_model_favors_dog():
    assert spread_recommendation(-0.5, -1.5) == "AWAY"


def test_grade_moneyline_uses_edge_pick_not_win_prob():
    assert grade_moneyline("AWAY", winner="home") is False
    assert grade_moneyline("HOME", winner="home") is True
    assert grade_moneyline("NO_PLAY", winner="home") is None


def test_grade_spread_home_cover():
    assert (
        grade_spread(
            "HOME",
            home_score=5,
            away_score=2,
            market_spread_home=-1.5,
        )
        is True
    )


def test_grade_total_over():
    assert (
        grade_total(
            "OVER",
            total_runs=10,
            market_total=8.5,
            projected_total=9.0,
        )
        is True
    )


def test_enrich_row_adds_spread_pick_and_grades():
    row = enrich_game_projection_row(
        {
            "run_line": 2.0,
            "market_spread": -1.5,
            "ml_recommendation": "HOME",
            "total_recommendation": "OVER",
            "market_total": 8.5,
            "projected_total": 9.0,
            "actual_home_score": 6,
            "actual_away_score": 3,
            "actual_winner": "home",
        }
    )
    assert row["spread_recommendation"] == "HOME"
    assert row["ml_correct"] is True
    assert row["spread_correct"] is True
    assert row["total_correct"] is True
