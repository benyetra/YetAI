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


@pytest.mark.asyncio
async def test_seeded_slate_publishes_three_gradeable_picks(sqlite_db):
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
            prediction_date=datetime(2026, 5, 22, 12, 0),
        )
    )
    sqlite_db.commit()

    result = await AutoPickOrchestrator(
        db=sqlite_db, providers=_build_providers(sqlite_db), now=NOW
    ).run()

    bets = sqlite_db.query(YetAIBet).all()
    assert result.pick_count == 3, sqlite_db.query(AutoPickRun).one().dropped_reasons
    assert [b.status for b in bets] == ["active"] * 3
    by_league = {(b.sport, b.prediction_factors["grading"]["market"]) for b in bets}
    assert by_league == {("NBA", "spread"), ("NHL", "total")}
    for b in bets:
        g = b.prediction_factors["grading"]
        assert _can_grade(g["league"], g["market"], g.get("stat"))
        assert g["game_date"] == "2026-05-22" and g["home_team"] and g["away_team"]
        assert g["side"] in ("home", "away", "over", "under")
        assert b.commence_time is not None and b.commence_time > NOW
    nhl = next(b for b in bets if b.sport == "NHL")
    assert nhl.commence_time == datetime(2026, 5, 22, 23, 0)  # 19:00 ET -> UTC
    assert nhl.prediction_factors["grading"]["line"] == 5.5
    assert nhl.home_team == "Boston Bruins"
    assert nhl.prediction_factors["grading"]["away_team"] == "Toronto Maple Leafs"

    away = next(b for b in bets if b.prediction_factors["grading"]["side"] == "away")
    assert away.prediction_factors["grading"]["line"] == 2.0  # picked side's spread
