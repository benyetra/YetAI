"""Offline NHL goalie saves: real writer on saved real payloads -> auto-pick -> grading.

Game: NYR @ VAN (NHL 2026020310, 21:00 ET 2026-11-13). ESPN scoreboard lists Dylan
Garand (NYR) as confirmed and Leevi Merilainen (VAN) as expected (probable).
"""

import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.database_models import AutoPickRun, YetAIBet
from app.models.predictions_models import NHLGoalie, NHLGoaliePredictions
from app.services import espn_results as er
from app.services import yetai_grading as yg
from app.services.auto_pick.orchestrator import AutoPickOrchestrator
from app.services.etl.nhl import confirm_starters as cs
from app.services.etl.nhl import daily_predictions as dp
from app.services.etl.nhl.nhl_api_client import NHLAPIClient
from app.tasks.auto_pick import _build_providers

FIX = Path(__file__).parent.parent / "fixtures" / "nhl"
DAY = date(2026, 11, 13)
NOW = datetime(2026, 11, 13, 21, 45)  # 16:45 ET, game at 02:00Z next day


def _load(name):
    return json.loads((FIX / name).read_text())


GAME = {
    "id": 2026020310,
    "startTimeUTC": "2026-11-14T02:00:00Z",
    "gameState": "FUT",
    "homeTeam": {"id": 23, "abbrev": "VAN", "placeName": {"default": "Vancouver"}},
    "awayTeam": {"id": 3, "abbrev": "NYR", "placeName": {"default": "New York"}},
}
EVENTS = [
    {"id": "ev1", "away_team": "New York Rangers", "home_team": "Vancouver Canucks"}
]


def _odds_payload():
    def goalie(name, point, over, under):
        return [
            {"name": "Over", "description": name, "point": point, "price": over},
            {"name": "Under", "description": name, "point": point, "price": under},
        ]

    return {
        "bookmakers": [
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "player_total_saves",
                        "outcomes": goalie("Dylan Garand", 25.5, -115, -105)
                        + goalie("Leevi Merilainen", 24.5, -110, -110),
                    }
                ],
            }
        ]
    }


@pytest.fixture
def written(sqlite_db, monkeypatch):
    """Run the real writer; only I/O (NHL API, ESPN, Odds API, model) is faked."""
    for gid, name, tid, team in (
        (8482193, "D. Garand", 3, "New York"),
        (8482447, "L. Meriläinen", 23, "Vancouver"),
    ):
        sqlite_db.add(NHLGoalie(player_id=gid, name=name, team_id=tid, team_name=team))
    sqlite_db.commit()
    for mod in (dp, cs):
        monkeypatch.setattr(mod, "db_session", sqlite_db)
    monkeypatch.setattr(
        dp,
        "predict_goalie_saves",
        lambda **kw: {
            "predicted_saves": 29.0,
            "predicted_shots_against": 31.5,
            "predicted_save_pct": 0.92,
            "confidence": 80.0,
        },
    )
    monkeypatch.setattr(
        NHLAPIClient, "get_game_boxscore", lambda self, gid: {"gameState": "FUT"}
    )
    monkeypatch.setattr(
        NHLAPIClient,
        "get_team_roster",
        lambda self, abbrev: _load(f"nhl_roster_{abbrev}.json"),
    )
    monkeypatch.setattr(
        cs.requests,
        "get",
        lambda *a, **k: type(
            "R",
            (),
            {
                "raise_for_status": lambda s: None,
                "json": lambda s: _load("espn_nhl_scoreboard_20261113.json"),
            },
        )(),
    )
    with patch(
        "app.services.etl.nhl.generate_daily_predictions._fetch_nhl_event_odds_payload",
        return_value=_odds_payload(),
    ):
        assert dp.generate_goalie_predictions([GAME], EVENTS) == 2
    return sqlite_db


async def _run(db):
    res = await AutoPickOrchestrator(
        db=db, providers=_build_providers(db), now=NOW
    ).run()
    return res, db.query(YetAIBet).all()


def test_writer_rows_carry_method_and_full_name(written):
    rows = {r.team_id: r for r in written.query(NHLGoaliePredictions).all()}
    nyr, van = rows[3], rows[23]
    assert nyr.features_used["starter_confirmation"]["method"] == "confirmed"
    assert nyr.features_used["starter_confirmation"]["full_name"] == "Dylan Garand"
    assert van.features_used["starter_confirmation"]["method"] == "probable"
    assert (nyr.saves_line, nyr.confidence) == (25.5, 76.0)  # 80 * 0.95
    assert van.confidence == 56.0  # 80 * 0.70: probable scores lower


@pytest.mark.asyncio
async def test_confirmed_goalie_publishes_graded_pick(written, monkeypatch):
    monkeypatch.delenv("NHL_GOALIE_PROBABLE_PICKS", raising=False)
    res, bets = await _run(written)
    (b,) = [b for b in bets if b.sport == "NHL"]  # probable VAN goalie is not picked
    assert b.status == "active"
    assert b.prediction_factors["grading"] == {
        "market": "player_prop",
        "league": "NHL",
        "stat": "saves",
        "player": "Dylan Garand",
        "home_team": "Vancouver Canucks",
        "away_team": "New York Rangers",
        "side": "over",
        "line": 25.5,
        "game_date": "2026-11-13",
    }
    assert yg.can_grade("NHL", "player_prop", "saves")
    assert b.commence_time == datetime(2026, 11, 14, 2, 0) and b.commence_time > NOW


@pytest.mark.asyncio
async def test_probable_goalie_publishes_only_with_flag(written, monkeypatch):
    monkeypatch.setenv("NHL_GOALIE_PROBABLE_PICKS", "1")
    res, bets = await _run(written)
    # Same game: one pick per event (event_already_used), so one of the two goalies
    # is published; with the flag the probable VAN goalie is a candidate too.
    assert len([b for b in bets if b.sport == "NHL"]) == 1
    run = written.query(AutoPickRun).one()
    assert run.candidates_considered == 2


def _espn_void_setup(monkeypatch):
    board = _load("espn_nhl_scoreboard_20261112.json")
    summary = _load("espn_nhl_summary_401891808.json")

    def fake(url, params=None):
        if url.endswith("/summary"):
            return summary
        return board

    er.clear_cache()
    monkeypatch.setattr(er, "_get_json", fake)


class _Bet:
    sport = "NHL"
    bet_type = "player_prop"
    selection = "Joey Daccord Over 24.5 Saves"
    home_team = "Seattle Kraken"
    away_team = "Carolina Hurricanes"
    commence_time = datetime(2026, 11, 12, 17, 0)
    prediction_factors = {
        "grading": {
            "market": "player_prop",
            "league": "NHL",
            "stat": "saves",
            "player": "Joey Daccord",  # backup: only the starters are in the box score
            "home_team": "Seattle Kraken",
            "away_team": "Carolina Hurricanes",
            "side": "over",
            "line": 24.5,
            "game_date": "2026-11-12",
        }
    }


def test_goalie_who_did_not_start_is_not_found_in_real_box_score(monkeypatch):
    _espn_void_setup(monkeypatch)
    starter = _Bet()
    starter.prediction_factors = {
        "grading": {**_Bet.prediction_factors["grading"], "player": "Philipp Grubauer"}
    }
    assert yg.grade_pick(starter).kind in ("won", "lost")  # 26 saves vs 24.5
    # A goalie who did not dress is "not in box score": the grader returns not_ready,
    # not void. The settlement loop turns that into void once the retry window ends.
    out = yg.grade_pick(_Bet())
    assert (out.kind, out.result) == (
        "not_ready",
        "Player not in box score: Joey Daccord",
    )


def test_goalie_who_did_not_start_settles_void_after_retry_window(
    sqlite_db, monkeypatch
):
    from app.models.database_models import BetSource, BetType, SubscriptionTier
    from app.services.yetai_bets_service_db import YetAIBetsServiceDB

    _espn_void_setup(monkeypatch)
    monkeypatch.delenv("YETAI_SETTLE_RETRY_DAYS", raising=False)  # default 3 days
    bet = YetAIBet(
        id="nhl-void-1",
        title="t",
        description="",
        sport="NHL",
        source=BetSource.AUTO,
        bet_type=BetType.PROP,
        selection=_Bet.selection,
        odds=-110,
        confidence=80,
        status="active",
        tier_requirement=SubscriptionTier.FREE,
        home_team=_Bet.home_team,
        away_team=_Bet.away_team,
        commence_time=_Bet.commence_time,
        created_at=datetime(2026, 11, 12, 15, 0),
        prediction_factors=dict(_Bet.prediction_factors),
    )
    sqlite_db.add(bet)
    sqlite_db.commit()
    svc = YetAIBetsServiceDB()
    # Waits through the retry window (from the first attempt, 11-13 + 3 days), then void.
    assert svc._settle_one(sqlite_db, bet, datetime(2026, 11, 13, 12, 0)) == "pending"
    assert svc._settle_one(sqlite_db, bet, datetime(2026, 11, 17, 12, 0)) == "void"
    assert bet.status == "void"
    assert "Player not in box score: Joey Daccord" in (bet.result or "")
