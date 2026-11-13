"""Round-2 review fixes around settlement: game time, void mirror, legacy rows, retries."""

import copy
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.data.celery_tasks import ADMIN_FIREABLE_TASKS, FIREABLE_CATALOG
from app.models.database_models import YetAIBet
from app.models.simple_unified_bet_model import BetStatus
from app.services import espn_results as er
from app.services.yetai_bets_service_db import (
    YetAIBetsServiceDB,
    format_game_time_et,
    yetai_pick_gradeable,
)
from tests.test_espn_results import EVENT, _load, espn  # noqa: F401
from tests.test_yetai_grading import meta
from tests.test_yetai_settlement import FakeDB, mk

SERVICE = YetAIBetsServiceDB()

# --- game time is Eastern, not UTC labelled EDT -------------------------------


@pytest.mark.parametrize(
    "utc,want",
    [
        (datetime(2026, 11, 14, 0, 30), "11/13/2026 @7:30 PM ET"),  # EST
        (datetime(2026, 7, 15, 23, 30), "07/15/2026 @7:30 PM ET"),  # EDT
        (
            datetime(2026, 1, 12, 3, 0),
            "01/11/2026 @10:00 PM ET",
        ),  # crosses midnight UTC
        (datetime(2026, 11, 14, 17, 0), "11/14/2026 @12:00 PM ET"),
    ],
)
def test_game_time_is_eastern(utc, want):
    assert format_game_time_et(utc) == want


def test_bet_dict_uses_eastern_game_time_and_keeps_the_iso_start():
    bet = mk(commence_time=datetime(2026, 11, 14, 0, 30), created_at=datetime.utcnow())
    d = SERVICE._yetai_bet_to_dict(bet)
    assert d["game_time"] == "11/13/2026 @7:30 PM ET"
    assert d["commence_time"].startswith("2026-11-14T00:30")
    assert SERVICE._yetai_bet_to_dict(mk(commence_time=None))["game_time"] == "TBD"


# --- void mirrors onto placed bets as cancelled/refunded ---------------------------


def _placed(status=BetStatus.PENDING):
    return SimpleNamespace(
        id="placed",
        yetai_bet_id=None,
        status=status,
        amount=100.0,
        potential_win=90.0,
        result_amount=0.0,
        reasoning=None,
        settled_at=None,
    )


def _pick(status, result="why"):
    return SimpleNamespace(id="pick", status=status, settled_at=None, result=result)


@pytest.mark.parametrize(
    "status,target,paid",
    [
        ("won", BetStatus.WON, 190.0),
        ("lost", BetStatus.LOST, 0.0),
        ("pushed", BetStatus.PUSHED, 100.0),
        ("void", BetStatus.CANCELLED, 100.0),
    ],
)
def test_pick_outcomes_mirror_to_placed_bets(status, target, paid):
    placed = _placed()
    assert SERVICE.sync_unified_from_yetai_pick(MagicMock(), _pick(status), placed)
    assert (placed.status, placed.result_amount) == (target, paid)
    assert placed.yetai_bet_id == "pick" and placed.reasoning == "why"


@pytest.mark.parametrize("status", [BetStatus.PENDING, BetStatus.LIVE])
def test_void_pick_cancels_a_still_open_placed_bet(status):
    placed = _placed(status)
    assert SERVICE.sync_unified_from_yetai_pick(MagicMock(), _pick("void"), placed)
    assert placed.status == BetStatus.CANCELLED and placed.result_amount == 100.0


@pytest.mark.parametrize(
    "status",
    [
        BetStatus.WON,
        BetStatus.LOST,
        BetStatus.PUSHED,
        BetStatus.CASHED_OUT,
        BetStatus.CANCELLED,
    ],
)
def test_void_pick_never_changes_a_settled_placed_bet(status):
    placed = _placed(status)
    assert not SERVICE.sync_unified_from_yetai_pick(MagicMock(), _pick("void"), placed)
    assert placed.status == status and placed.result_amount == 0.0


def test_unsettled_pick_does_not_touch_placed_bets():
    assert not SERVICE.sync_unified_from_yetai_pick(
        MagicMock(), _pick("active"), _placed()
    )


# --- rows with no date anywhere ------------------------------------------------------


def test_row_with_no_dates_at_all_settles_void_instead_of_waiting_forever():
    bet = mk(commence_time=None, created_at=None, prediction_factors={})
    assert yetai_pick_gradeable(bet)
    now = datetime(2026, 11, 13, 12)
    assert SERVICE._settle_one(FakeDB(), bet, now) == "void"
    assert bet.status == "void" and bet.result.startswith("Ungradeable")


# --- doubleheader and malformed payload through the settler (real payloads) -----------


def _dh_bet(espn):
    espn.boards[("mlb", "20260523")] = _load(
        "mlb_scoreboard_20260523_doubleheader.json"
    )
    g = {
        "market": "moneyline",
        "league": "MLB",
        "game_date": "2026-05-23",
        "home_team": "Cincinnati Reds",
        "away_team": "St. Louis Cardinals",
        "side": "home",
        "line": None,
    }
    return mk(
        sport="MLB",
        selection="Cincinnati Reds ML",
        home_team="Cincinnati Reds",
        away_team="St. Louis Cardinals",
        commence_time=None,
        created_at=datetime(2026, 5, 23, 12),
        prediction_factors={"grading": g},
    )


def test_doubleheader_pick_is_retried_in_the_window_then_voided_with_the_reason(espn):
    bet = _dh_bet(espn)
    assert SERVICE._settle_one(FakeDB(), bet, datetime(2026, 5, 24, 12)) == "pending"
    assert bet.status == "active"
    assert SERVICE._settle_one(FakeDB(), bet, datetime(2026, 6, 1, 12)) == "void"
    assert bet.status == "void" and "Doubleheader" in bet.result


def test_doubleheader_pick_with_a_start_time_settles_on_that_game(espn):
    bet = _dh_bet(espn)
    bet.commence_time = datetime(2026, 5, 23, 23, 15)
    assert SERVICE._settle_one(FakeDB(), bet, datetime(2026, 5, 24, 12)) == "settled"
    assert bet.status == "won"


def _malformed_board(espn):
    board = copy.deepcopy(espn.boards[("nba", "20260111")])
    board["events"].insert(0, copy.deepcopy(board["events"][0]))
    del board["events"][0]["competitions"][0]["competitors"][0]["team"]
    espn.boards[("nba", "20260111")] = board


def _nba_bet():
    return mk(
        selection="Over 200.5",
        commence_time=datetime(2026, 1, 12, 0, 0),
        created_at=datetime(2026, 1, 11),
        prediction_factors={"grading": meta("NBA", "total", "over", 200.5)},
    )


def test_malformed_espn_payload_keeps_retrying_and_voids_only_at_the_backstop(espn):
    _malformed_board(espn)
    bet = _nba_bet()
    assert SERVICE._settle_one(FakeDB(), bet, datetime(2026, 1, 20, 12)) == "pending"
    assert bet.status == "active"
    assert bet.prediction_factors["settlement"]["last_kind"] == "error"
    assert SERVICE._settle_one(FakeDB(), bet, datetime(2026, 2, 20, 12)) == "void"


def test_bad_pick_metadata_still_voids_immediately(espn):
    bet = _nba_bet()
    bet.prediction_factors = {
        "grading": {**meta("NBA", "total", "over", 1), "home_team": 7}
    }
    assert SERVICE._settle_one(FakeDB(), bet, datetime(2026, 1, 12, 12)) == "void"


# --- admin can fire settlement ---------------------------------------------------------


def test_settle_task_is_admin_fireable_with_a_catalog_row():
    from app.tasks.settle_yetai_bets import settle_yetai_bets

    assert settle_yetai_bets.name == "yetai_bets.settle"
    assert ADMIN_FIREABLE_TASKS["yetai_bets.settle"] > 0
    assert any(r["task_name"] == "yetai_bets.settle" for r in FIREABLE_CATALOG)
