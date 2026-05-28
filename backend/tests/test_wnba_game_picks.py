"""Unit tests for WNBA game actuals enrichment."""

from app.services.wnba_game_picks import (
    WnbaGameActual,
    ats_covered,
    enrich_spread_projection_row,
    enrich_totals_projection_row,
)


def test_ats_covered_home_wins_spread():
    assert ats_covered("HOME", 8, -5.5) is True
    assert ats_covered("AWAY", 8, -5.5) is False


def test_ats_covered_push_returns_none():
    assert ats_covered("HOME", 5, -5.0) is None


def test_enrich_spread_row_attaches_scores_and_grades():
    actual = WnbaGameActual(
        home_score=90,
        away_score=82,
        actual_margin=8,
        home_won=True,
        actual_total=172,
    )
    row = {
        "recommendation": "HOME",
        "market_spread_home": -5.5,
    }
    out = enrich_spread_projection_row(row, actual)
    assert out["actual_home_score"] == 90
    assert out["actual_away_score"] == 82
    assert out["actual_winner"] == "home"
    assert out["spread_correct"] is True
    assert out["ml_correct"] is True


def test_enrich_totals_row_grades_over_under():
    actual = WnbaGameActual(
        home_score=88,
        away_score=80,
        actual_margin=8,
        home_won=True,
        actual_total=168,
    )
    row = {
        "recommendation": "OVER",
        "market_total": 165.5,
        "projected_total": 170.0,
    }
    out = enrich_totals_projection_row(row, actual)
    assert out["actual_total"] == 168
    assert out["actual_total_runs"] == 168
    assert out["total_correct"] is True


def test_enrich_spread_row_without_actual_is_unchanged():
    row = {"recommendation": "HOME"}
    assert enrich_spread_projection_row(row, None) == row
