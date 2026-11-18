"""Offline end-to-end: seeded projection rows -> real sources/providers -> 3 active picks."""

from datetime import date, datetime

import pytest

from app.models.database_models import AutoPickRun, YetAIBet
from app.models.predictions_models import (
    NBAGameLines,
    NBASpreadProjections,
    NHLTeamTotalsPredictions,
)
from app.services.auto_pick.orchestrator import AutoPickOrchestrator
from app.services.yetai_grading import can_grade as _can_grade  # real gate
from app.tasks.auto_pick import _build_providers

NOW = datetime(2026, 5, 22, 15, 0)  # 11:00 ET
DAY = date(2026, 5, 22)


def _nba_game(db, home, away, margin, spread_home, rec, utc_tip):
    db.add(
        NBASpreadProjections(
            game_date=DAY,
            home_team_name=home,
            away_team_name=away,
            projected_margin=margin,
            home_win_prob=0.5,
            market_spread_home=spread_home,
            recommendation=rec,
            created_at=datetime(2026, 5, 22, 12, 0),
        )
    )
    db.add(
        NBAGameLines(
            game_date=DAY,
            home_team_name=home,
            away_team_name=away,
            game_time=utc_tip,
            spread_home=spread_home,
            spread_away=-spread_home,
            last_updated=datetime(2026, 5, 22, 12, 0),
            spread_home_odds=-110,
            spread_away_odds=-110,
        )
    )


def _seed_slate(sqlite_db):
    # Home -4 but model has home by 9 -> HOME covers by 5.
    _nba_game(
        sqlite_db,
        "Boston Celtics",
        "Miami Heat",
        9.0,
        -4.0,
        "HOME",
        datetime(2026, 5, 22, 23, 30),
    )
    # Home -2 but model has AWAY by 6 -> AWAY +2 covers by 8.
    _nba_game(
        sqlite_db,
        "Denver Nuggets",
        "Utah Jazz",
        -6.0,
        -2.0,
        "AWAY",
        datetime(2026, 5, 23, 1, 0),
    )
    sqlite_db.add(
        NHLTeamTotalsPredictions(
            game_date=DAY,
            game_time_et=datetime(2026, 5, 22, 19, 0),  # naive ET
            # Writer format (etl/nhl/daily_predictions.py): place names + ids,
            # recommendation "OVER <line>".
            home_team_id=6,
            home_team_name="Boston",
            away_team_id=10,
            away_team_name="Toronto",
            predicted_home_goals=5.0,
            predicted_away_goals=5.0,
            predicted_total_goals=10.0,
            suggested_ou_line=6.0,
            draftkings_ou_line=5.5,
            over_odds=-110,
            under_odds=-110,
            confidence=80.0,
            betting_recommendation="OVER 5.5",
            prediction_date=datetime(2026, 5, 22, 14, 50),  # after the 10:45 ET refresh
        )
    )
    sqlite_db.commit()


@pytest.mark.asyncio
async def test_nhl_key_without_record_is_reported_withheld(sqlite_db):
    _seed_slate(sqlite_db)
    result = await AutoPickOrchestrator(
        db=sqlite_db, providers=_build_providers(sqlite_db), now=NOW
    ).run()
    assert result.pick_count == 0 and sqlite_db.query(YetAIBet).count() == 0
    dropped = sqlite_db.query(AutoPickRun).one().dropped_reasons
    assert dropped["withheld_keys"]["NHL/total"]["reason"] == "unproven_record"
    assert dropped["withheld_keys"]["NHL/total"]["prove_in"] is True


@pytest.mark.asyncio
async def test_seeded_spread_and_total_slate_publishes_nothing(sqlite_db, monkeypatch):
    # Real sources and providers build 3 candidates (2 NBA spreads, 1 NHL total) with real
    # grading support, but the spread and the total have no consensus price and no probability
    # model, so the EV gate drops them all: the system publishes nothing it cannot price.
    monkeypatch.setenv("AUTO_PICK_PROVE_IN_KEYS", "")
    monkeypatch.setenv("AUTO_PICK_REQUIRE_PROVEN_RECORD", "false")
    _seed_slate(sqlite_db)
    result = await AutoPickOrchestrator(
        db=sqlite_db, providers=_build_providers(sqlite_db), now=NOW
    ).run()

    run = sqlite_db.query(AutoPickRun).one()
    assert run.candidates_considered == 3
    assert result.pick_count == 0 and sqlite_db.query(YetAIBet).count() == 0
    assert run.dropped_reasons["counts"] == {"no_consensus_price": 3}
    assert _can_grade("NBA", "spread", None) and _can_grade("NHL", "total", None)
