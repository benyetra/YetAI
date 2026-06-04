"""Tests for YetAI parlay verification."""

from datetime import date, datetime
from unittest.mock import MagicMock

from app.models.database_models import BetType, YetAIBet
from app.services.yetai_bets_service_db import YetAIBetsServiceDB
from app.services.yetai_parlay_verification import (
    combine_parlay_leg_statuses,
    game_date_for_parlay_leg,
    normalize_leg_bet_type,
    verify_yetai_parlay,
    yetai_bet_from_parlay_leg,
)


def test_normalize_leg_bet_type_variants():
    assert normalize_leg_bet_type("Spread") == BetType.SPREAD
    assert normalize_leg_bet_type("Moneyline") == BetType.MONEYLINE
    assert normalize_leg_bet_type("Player Prop") == BetType.PROP


def test_game_date_for_parlay_leg_prefers_commence_time():
    leg = {"commence_time": "2026-06-04T23:05:00+00:00", "game_id": "evt-1"}
    assert game_date_for_parlay_leg(leg) == date(2026, 6, 4)


def test_yetai_bet_from_parlay_leg_maps_fields():
    leg = {
        "sport": "MLB",
        "game": "Rockies @ Phillies",
        "game_id": "mlb-game-2",
        "home_team": "Philadelphia Phillies",
        "away_team": "Colorado Rockies",
        "bet_type": "Moneyline",
        "pick": "Colorado Rockies ML",
        "odds": "+145",
        "confidence": 82,
        "commence_time": "2026-06-04T23:05:00+00:00",
    }
    synthetic = yetai_bet_from_parlay_leg(leg)
    assert synthetic.bet_type == BetType.MONEYLINE
    assert synthetic.selection == "Colorado Rockies ML"
    assert synthetic.home_team == "Philadelphia Phillies"


def test_combine_parlay_leg_statuses_rules():
    assert combine_parlay_leg_statuses(["won", "won"]) == (
        "won",
        "Parlay won: all 2 active legs won",
    )
    assert combine_parlay_leg_statuses(["won", "lost"]) == (
        "lost",
        "Parlay lost: 1 of 2 legs lost",
    )
    assert combine_parlay_leg_statuses(["won", "pending"]) is None


def test_verify_yetai_parlay_settles_when_both_legs_grade():
    service = YetAIBetsServiceDB()
    prop_service = MagicMock()
    db = MagicMock()

    parlay = YetAIBet(
        id="parlay-1",
        title="2-Leg Parlay (+450)",
        description="",
        bet_type=BetType.PARLAY,
        selection="2-Leg Parlay",
        odds=450,
        confidence=80,
        sport="Multi-Sport",
        parlay_legs=[
            {
                "sport": "MLB",
                "bet_type": "Spread",
                "pick": "Philadelphia Phillies +3.5",
                "home_team": "Philadelphia Phillies",
                "away_team": "Colorado Rockies",
                "game_id": "game-1",
                "odds": "-110",
            },
            {
                "sport": "MLB",
                "bet_type": "Moneyline",
                "pick": "Colorado Rockies ML",
                "home_team": "Philadelphia Phillies",
                "away_team": "Colorado Rockies",
                "game_id": "game-2",
                "odds": "+145",
            },
        ],
    )

    service._evaluate_yetai_bet_outcome = MagicMock(
        side_effect=[
            ("won", "Phillies covered"),
            ("won", "Rockies won"),
        ]
    )

    def _fake_verify_leg(leg, svc, props, session):
        synthetic = yetai_bet_from_parlay_leg(leg)
        if synthetic.bet_type == BetType.SPREAD:
            return ("won", "Phillies covered")
        return ("won", "Rockies won")

    import app.services.yetai_parlay_verification as mod

    original = mod.verify_parlay_leg
    mod.verify_parlay_leg = _fake_verify_leg
    try:
        outcome = verify_yetai_parlay(parlay, service, prop_service, db)
    finally:
        mod.verify_parlay_leg = original

    assert outcome is not None
    status, result, legs = outcome
    assert status == "won"
    assert legs[0]["leg_status"] == "won"
    assert legs[1]["leg_status"] == "won"
    assert "Parlay won" in result


def test_verify_yetai_parlay_stays_pending_until_all_legs_ready():
    service = YetAIBetsServiceDB()
    prop_service = MagicMock()
    db = MagicMock()
    parlay = YetAIBet(
        id="parlay-2",
        title="2-Leg Parlay",
        description="",
        bet_type=BetType.PARLAY,
        selection="2-Leg Parlay",
        odds=264,
        confidence=80,
        parlay_legs=[
            {
                "sport": "NHL",
                "bet_type": "Spread",
                "pick": "Bruins +2.5",
                "odds": "-110",
            },
            {
                "sport": "MLB",
                "bet_type": "Player Prop",
                "pick": "Shohei Ohtani OVER 4.5 strikeouts",
                "odds": "-110",
            },
        ],
    )

    import app.services.yetai_parlay_verification as mod

    original = mod.verify_parlay_leg
    mod.verify_parlay_leg = lambda *args, **kwargs: None
    try:
        assert verify_yetai_parlay(parlay, service, prop_service, db) is None
    finally:
        mod.verify_parlay_leg = original
