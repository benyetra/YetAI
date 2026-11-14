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


def _spread(pick, home, away, line):
    return grade_spread(pick, home_score=home, away_score=away, market_spread_home=line)


def test_grade_spread_pins_sign_home_favourite():
    # home -1.5 wins by 1: does NOT cover, so HOME loses and AWAY wins
    assert _spread("HOME", 5, 4, -1.5) is False
    assert _spread("AWAY", 5, 4, -1.5) is True
    # home -1.5 wins by 2: covers
    assert _spread("HOME", 5, 3, -1.5) is True
    assert _spread("AWAY", 5, 3, -1.5) is False


def test_grade_spread_pins_sign_home_underdog():
    # home +1.5 loses by 1: covers, HOME wins
    assert _spread("HOME", 4, 5, 1.5) is True
    assert _spread("AWAY", 4, 5, 1.5) is False
    # home +1.5 loses by 2: does not cover
    assert _spread("HOME", 3, 5, 1.5) is False
    assert _spread("AWAY", 3, 5, 1.5) is True


def test_grade_spread_push_when_margin_exactly_matches_line():
    assert _spread("HOME", 5, 3, -2.0) is None
    assert _spread("AWAY", 5, 3, -2.0) is None
    assert _spread("HOME", 3, 5, 2.0) is None


def test_spread_pick_agrees_with_grader_sign():
    # Model projects home by 2.0 vs market home -1.5 -> HOME; winning by 3 covers.
    assert spread_recommendation(2.0, -1.5) == "HOME"
    assert _spread("HOME", 6, 3, -1.5) is True
    # Model projects home by 0 vs market home -1.5 -> AWAY; home winning by 1 loses ATS.
    assert spread_recommendation(0.0, -1.5) == "AWAY"
    assert _spread("AWAY", 5, 4, -1.5) is True


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
