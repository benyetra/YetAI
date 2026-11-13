"""Tests for YetAI parlay verification."""

from datetime import date, datetime, timedelta
from unittest.mock import patch

from app.models.database_models import BetType, YetAIBet
from app.services.yetai_grading import Outcome
from app.services.yetai_parlay_verification import (
    _leg_as_bet,
    combine_parlay_leg_statuses,
    game_date_for_parlay_leg,
    grade_parlay,
    normalize_leg_bet_type,
)

NOW = datetime(2026, 6, 10, 12, 0)


def test_normalize_leg_bet_type_variants():
    assert normalize_leg_bet_type("Spread") == BetType.SPREAD
    assert normalize_leg_bet_type("Moneyline") == BetType.MONEYLINE
    assert normalize_leg_bet_type("Player Prop") == BetType.PROP


def test_leg_date_order_grading_then_commence_then_parent_never_today():
    both = {
        "grading": {"market": "spread", "league": "MLB", "game_date": "2026-06-03"},
        "commence_time": "2026-06-04T23:05:00+00:00",
    }
    assert game_date_for_parlay_leg(both) == date(2026, 6, 3)
    assert game_date_for_parlay_leg({"commence_time": "2026-06-04T23:05:00+00:00"}) == (
        date(2026, 6, 4)
    )
    parent = YetAIBet(commence_time=datetime(2026, 6, 2, 23, 0))
    assert game_date_for_parlay_leg({"pick": "x"}, parent) == date(2026, 6, 2)
    assert game_date_for_parlay_leg({"pick": "x"}) is None  # never falls back to today


def test_leg_as_bet_maps_fields_and_grading():
    grading = {"market": "moneyline", "league": "MLB"}
    leg = {
        "sport": "MLB",
        "game_id": "mlb-game-2",
        "home_team": "Philadelphia Phillies",
        "away_team": "Colorado Rockies",
        "bet_type": "Moneyline",
        "pick": "Colorado Rockies ML",
        "grading": grading,
    }
    synthetic = _leg_as_bet(leg)
    assert synthetic.bet_type == BetType.MONEYLINE
    assert synthetic.selection == "Colorado Rockies ML"
    assert synthetic.prediction_factors == {
        "grading": grading,
        "event_id": "mlb-game-2",
    }


def test_combine_parlay_leg_statuses_rules():
    assert combine_parlay_leg_statuses(["won", "won"]) == (
        "won",
        "Parlay won: all 2 active legs won",
    )
    assert combine_parlay_leg_statuses(["won", "lost"]) == (
        "lost",
        "Parlay lost: 1 of 2 legs lost",
    )
    assert combine_parlay_leg_statuses(["lost", "pending"])[0] == "lost"
    assert combine_parlay_leg_statuses(["won", "pending"]) is None
    assert combine_parlay_leg_statuses(["won", "void", "pushed"])[0] == "won"
    assert combine_parlay_leg_statuses(["void", "pushed"])[0] == "void"
    assert (
        combine_parlay_leg_statuses(["pushed", "pushed"])[0] == "void"
    )  # no live legs
    assert combine_parlay_leg_statuses(["void", "void"])[0] == "void"


def _parlay(*legs):
    return YetAIBet(
        id="parlay-1",
        title="Parlay",
        description="",
        bet_type=BetType.PARLAY,
        selection="Parlay",
        odds=450,
        confidence=80,
        created_at=NOW - timedelta(days=1),
        parlay_legs=[
            {"sport": "MLB", "bet_type": "Spread", "pick": f"P{i}", **leg}
            for i, leg in enumerate(legs)
        ],
    )


def _grade(parlay, *outcomes):
    with patch(
        "app.services.yetai_grading.grade_pick", side_effect=list(outcomes)
    ) as grade:
        return grade_parlay(parlay, NOW), grade


def test_grade_parlay_won_annotates_every_leg():
    (outcome, legs), _ = _grade(
        _parlay({}, {}), Outcome("won", "a"), Outcome("won", "b")
    )
    assert outcome.kind == "won" and "Parlay won" in outcome.result
    assert [leg["leg_status"] for leg in legs] == ["won", "won"]
    assert legs[0]["leg_result"] == "a"


def test_grade_parlay_not_ready_until_all_legs_ready():
    (outcome, legs), _ = _grade(
        _parlay({}, {}), Outcome("won", "a"), Outcome("not_ready", "Game not found")
    )
    assert outcome.kind == "not_ready"
    assert legs[1]["leg_status"] == "pending"


def test_grade_parlay_past_window_voids_pending_leg():
    old = {"commence_time": (NOW - timedelta(days=9)).isoformat()}
    (outcome, legs), _ = _grade(
        _parlay(old, old), Outcome("lost", "a"), Outcome("not_ready", "Game not found")
    )
    assert outcome.kind == "lost"
    (outcome, legs), _ = _grade(
        _parlay(old, old), Outcome("won", "a"), Outcome("not_ready", "Game not found")
    )
    assert outcome.kind == "won" and legs[1]["leg_status"] == "void"
    assert legs[1]["leg_result"] == "Ungradeable: Game not found"
