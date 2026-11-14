"""Legacy voided auto props (opponent only) are regraded through the normal settle path."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.database_models import BetSource, BetType, SubscriptionTier, YetAIBet
from app.models.simple_unified_bet_model import BetStatus
from app.models.simple_unified_bet_model import BetType as UBetType
from app.models.simple_unified_bet_model import SimpleUnifiedBet
from scripts.yetai_regrade_legacy_props import regrade
from tests.test_espn_results import espn  # noqa: F401

NOW = datetime.utcnow()


@compiles(JSONB, "sqlite")
def _jsonb(type_, compiler, **kw):  # noqa: ARG001
    return "JSON"


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    YetAIBet.__table__.create(engine)
    SimpleUnifiedBet.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def legacy(db, opponent="Toronto Raptors", line=12.5):
    # Kelly Oubre Jr. (76ers) scored 13 vs the Raptors on 2026-01-11 in the fixtures
    bet = YetAIBet(
        id="legacy-1",
        title="vs " + opponent,
        description="",
        odds=-110,
        confidence=80,
        tier_requirement=SubscriptionTier.FREE,
        bet_type=BetType.PROP,
        source=BetSource.AUTO,
        sport="NBA",
        selection=f"Kelly Oubre Jr. OVER {line} points",
        status="void",
        result="Ungradeable: Could not parse pick",
        settled_at=NOW - timedelta(days=1),
        created_at=NOW - timedelta(days=60),
        prediction_factors={
            "market_line": line,
            "event_id": "nba-prop-2026-01-11-1-points",
            "projection_metadata": {
                "stat": "points",
                "side": "over",
                "player": "Kelly Oubre Jr.",
                "opponent": opponent,
                "opponent_team_name": opponent,
            },
            "settlement": {"last_kind": "ungradeable"},
        },
    )
    copy = SimpleUnifiedBet(
        id="copy-1",
        user_id=1,
        odds_api_event_id="yetai-pick-legacy-1",
        yetai_bet_id="legacy-1",
        bet_type=UBetType.PROP,
        selection=bet.selection,
        sport="NBA",
        home_team="Toronto Raptors",
        away_team="Philadelphia 76ers",
        commence_time=NOW - timedelta(days=60),
        amount=100.0,
        odds=-110,
        potential_win=90.0,
        status=BetStatus.PENDING,
    )
    db.add_all([bet, copy])
    db.commit()
    return bet, copy


def test_dry_run_writes_nothing_then_apply_settles_and_is_idempotent(db, espn):
    bet, copy = legacy(db)
    out = regrade(db, apply=False)
    assert len(out) == 1 and "grader=won" in out[0] and "copies=1" in out[0]
    db.expire_all()
    assert bet.status == "void" and "grading" not in bet.prediction_factors
    assert copy.status == BetStatus.PENDING

    assert "APPLIED -> won" in regrade(db, apply=True)[0]
    db.expire_all()
    assert bet.status == "won" and bet.settled_at
    assert bet.prediction_factors["grading"]["home_team"] == "Toronto Raptors"
    assert copy.status == BetStatus.WON

    assert regrade(db, apply=True) == []  # no longer a candidate


def test_opponent_without_game_is_unresolved_and_untouched(db, espn):
    bet, copy = legacy(db, opponent="Boston Celtics")
    out = regrade(db, apply=True)
    assert len(out) == 1 and "UNRESOLVED" in out[0]
    db.expire_all()
    assert bet.status == "void" and bet.result.startswith("Ungradeable")
    assert copy.status == BetStatus.PENDING
