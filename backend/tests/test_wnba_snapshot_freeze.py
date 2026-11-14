"""WNBA writers freeze a game's rows once it starts (finding H-2).

Start time is WNBAGameLines.game_time (naive UTC). ``NOW_PRE``/``NOW_POST``
bracket a 23:00 UTC tip-off; nothing here reads the wall clock.
"""

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.models.predictions_models import (
    WNBAGameLines,
    WNBAPointsProjections,
    WNBASpreadProjections,
)
from app.services.etl.wnba import _prop_lines as pl
from app.services.etl.wnba import spread_projector as sp
from app.services.etl.wnba import totals_projector as tp
from app.services.etl.wnba import update_game_lines as ugl

DAY = date(2026, 6, 15)
TIP = datetime(2026, 6, 15, 23, 0)  # naive UTC
NOW_PRE = datetime(2026, 6, 15, 22, 0, tzinfo=timezone.utc)
NOW_POST = datetime(2026, 6, 15, 23, 30, tzinfo=timezone.utc)
ET = ZoneInfo("America/New_York")


def _game(**kw):
    vals = dict(
        game_date=DAY,
        game_time=TIP,
        home_team_name="Home",
        away_team_name="Away",
        home_team_id=1,
        away_team_id=2,
        spread_home=-3.5,
        total=160.5,
    )
    vals.update(kw)
    g = WNBAGameLines()
    for k, v in vals.items():
        setattr(g, k, v)
    return g


def _db(*result_lists):
    """Session whose successive .query().filter().all() calls return the lists."""
    db = MagicMock(name="Session")
    db.query.return_value.filter.return_value.all.side_effect = list(result_lists)
    return db


# ---- props -----------------------------------------------------------------


def _stored_prop(line=18.5, price=-110.0):
    r = WNBAPointsProjections()
    r.player_id, r.market_line, r.fanduel_price = 100, line, price
    return r


def _prop_row(line=None):
    return {
        "player_id": 100,
        "projected_points": 22.0,
        "market_line": line,
        "fanduel_price": None,
        "edge": None,
        "recommendation": "NO_PLAY",
        "confidence_score": None,
    }


ACTIVE = [SimpleNamespace(player_id=100, team_name="Home", opponent_team_name="Away")]


def _freeze(db, rows, now):
    return pl.freeze_prop_rows(
        db,
        WNBAPointsProjections,
        rows,
        stat="points",
        game_date=DAY,
        active_rows=ACTIVE,
        now=now,
    )


@pytest.mark.parametrize("fresh_line", [19.5, None])  # changed line / book has none
def test_started_game_props_not_written(fresh_line):
    db = _db([_game()], [_stored_prop()])
    assert _freeze(db, [_prop_row(fresh_line)], NOW_POST) == []


def test_started_game_prop_for_dropped_player_untouched():
    # player dropped from the active list: no row is built, so nothing is
    # upserted or deleted (generators never delete).
    db = _db([_game()], [])
    assert _freeze(db, [], NOW_POST) == []


def test_pre_start_missing_line_keeps_stored_line_and_rejudges():
    db = _db([_game()], [_stored_prop(18.5, -115.0)])
    (row,) = _freeze(db, [_prop_row(None)], NOW_PRE)
    assert row["market_line"] == 18.5
    assert row["fanduel_price"] == -115.0
    assert row["edge"] == 3.5
    assert row["recommendation"] == "OVER"
    assert row["confidence_score"] is not None


def test_pre_start_fresh_line_replaces_stored():
    db = _db([_game()])
    (row,) = _freeze(db, [_prop_row(19.5)], NOW_PRE)
    assert row["market_line"] == 19.5


def test_pre_start_no_line_anywhere_stays_no_play():
    db = _db([_game()], [])
    (row,) = _freeze(db, [_prop_row(None)], NOW_PRE)
    assert row["market_line"] is None and row["recommendation"] == "NO_PLAY"


# ---- game lines --------------------------------------------------------------


def _event(commence="2026-06-15T23:00:00Z", with_total=True):
    markets = [
        {
            "key": "totals",
            "outcomes": [
                {"name": "Over", "point": 161.5, "price": -110},
                {"name": "Under", "point": 161.5, "price": -110},
            ],
        }
    ]
    return {
        "id": "evt1",
        "commence_time": commence,
        "home_team": "Minnesota Lynx",
        "away_team": "Seattle Storm",
        "bookmakers": [{"markets": markets if with_total else []}],
    }


def _run_lines(events, stored, now):
    db = _db(stored)
    with (
        patch.object(ugl, "SessionLocal", lambda: db),
        patch.object(ugl, "_odds_get", return_value=events),
        patch.object(ugl, "upsert_many") as um,
    ):
        ugl.run(now=now)
    return um.call_args[0][2] if um.called else []


def test_started_game_line_not_rewritten_with_live_line():
    assert _run_lines([_event()], [], NOW_POST) == []


def test_pre_start_missing_market_keeps_stored_line():
    old = _game(home_team_name="Minnesota Lynx", away_team_name="Seattle Storm")
    old.total, old.over_odds, old.spread_home = 158.5, -105, None
    (row,) = _run_lines([_event(with_total=False)], [old], NOW_PRE)
    assert row["total"] == 158.5 and row["over_odds"] == -105
    assert row["spread_home"] is None  # nothing stored, nothing to keep


def test_pre_start_changed_line_updates():
    old = _game(home_team_name="Minnesota Lynx", away_team_name="Seattle Storm")
    old.total = 158.5
    (row,) = _run_lines([_event()], [old], NOW_PRE)
    assert row["total"] == 161.5


# ---- spreads / totals ----------------------------------------------------------


def _run_spreads(games, now):
    db = MagicMock(name="Session")
    db.query.return_value.order_by.return_value.all.return_value = []
    db.query.return_value.all.return_value = []
    db.query.return_value.filter.return_value.all.return_value = games
    with (
        patch.object(sp, "SessionLocal", lambda: db),
        patch.object(sp, "_load_elos", lambda d: {}),
        patch.object(sp, "now_eastern", lambda: now.astimezone(ET)),
        patch.object(sp, "upsert_many") as um,
    ):
        sp.run()
    return um.call_args[0][2]


def test_spread_projector_skips_started_game():
    assert _run_spreads([_game()], NOW_POST) == []


def test_spread_projector_projects_pre_start_game():
    (row,) = _run_spreads([_game()], NOW_PRE)
    assert row["market_spread_home"] == -3.5


def _run_totals(games, now):
    with (
        patch.object(tp, "now_eastern", lambda: now.astimezone(ET)),
        patch.object(tp, "get_todays_games", return_value=games),
        patch.object(tp, "generate_projection") as gp,
        patch.object(tp, "enrich_projection"),
        patch.object(tp, "save_projection") as save,
    ):
        gp.return_value = {
            "edge": None,
            "projected_total": 1.0,
            "market_total": 160.5,
            "home_team": "Home",
            "away_team": "Away",
            "recommendation": "NO_PLAY",
        }
        tp.generate_nightly_report(DAY)
    return save.call_count


def _tgame():
    return {
        "home_team": "Home",
        "away_team": "Away",
        "market_total": 160.5,
        "spread_home": -3.5,
        "game_time": TIP,
    }


def test_totals_projector_skips_started_game():
    assert _run_totals([_tgame()], NOW_POST) == 0


def test_totals_projector_saves_pre_start_game():
    assert _run_totals([_tgame()], NOW_PRE) == 1
