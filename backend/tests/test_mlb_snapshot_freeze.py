"""MLB snapshot freeze: started games are read-only, no-odds reruns keep the line."""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.etl.mlb import daily_projection_update as dpu
from app.services.etl.mlb import game_projection_pipeline as gpp

DAY = date(2026, 8, 5)
START = datetime(2026, 8, 5, 23, 5)  # naive UTC = 19:05 ET
BEFORE = datetime(2026, 8, 5, 20, 0, tzinfo=timezone.utc)
AFTER = datetime(2026, 8, 5, 23, 30, tzinfo=timezone.utc)


# ---------- strikeouts ----------
def _k_row(**kw):
    base = dict(
        projected_strikeouts=6.0,
        projected_innings_pitched=5.5,
        projected_at_bats=22.0,
        fanduel_line=5.5,
        fanduel_over_under="o",
        ev_over_under="o",
        k_edge=0.5,
        pick_confidence=60.0,
        matchup_source="observed",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _pitcher(**kw):
    base = dict(
        pitcher_id="1",
        name="P",
        projected_innings=5.0,
        projected_at_bats=20.0,
        projected_strikeouts=7.5,
        fanduel_point=6.5,
        fanduel_flag="u",
        matchup_source="observed",
        prob_over=None,
        pick_edge_pct=None,
        game_time=START,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _run_k(pitchers, row, now):
    session = MagicMock()
    pq = MagicMock()
    pq.all.return_value = pitchers
    so = MagicMock()
    so.filter_by.return_value.first.return_value = row

    session.query.side_effect = lambda m: pq if m is dpu.Pitcher else so
    with (
        patch.object(dpu, "db_session", session),
        patch.object(dpu, "resolve_mlb_strikeout_model_version", return_value="v"),
        patch.object(dpu, "attach_model_version"),
    ):
        dpu.store_projections(DAY, now=now)
    return session, so


def test_k_started_changed_line_is_frozen():
    row = _k_row()
    _run_k([_pitcher()], row, AFTER)
    assert (row.projected_strikeouts, row.fanduel_line, row.fanduel_over_under) == (
        6.0,
        5.5,
        "o",
    )


def test_k_started_no_line_is_frozen():
    row = _k_row()
    _run_k([_pitcher(fanduel_point=None)], row, AFTER)
    assert (row.fanduel_line, row.fanduel_over_under) == (5.5, "o")


def test_k_started_pitcher_dropped_row_not_deleted():
    row = _k_row()
    _, so = _run_k([_pitcher(pitcher_id="2")], row, AFTER)
    so.filter.assert_not_called()  # no stale-row delete path
    assert row.fanduel_line == 5.5


def test_k_prestart_scratch_row_not_deleted():
    row = _k_row()
    _, so = _run_k([_pitcher(pitcher_id="2")], row, BEFORE)
    so.filter.assert_not_called()
    so.filter.return_value.delete.assert_not_called()


def test_k_prestart_no_line_keeps_line_and_recomputes_side():
    row = _k_row()
    _run_k([_pitcher(fanduel_point=None, fanduel_flag="n")], row, BEFORE)
    assert row.fanduel_line == 5.5  # kept
    assert row.projected_strikeouts == 7.5  # refreshed
    assert row.fanduel_over_under == "over" or row.fanduel_over_under == "o"
    assert row.k_edge == 2.0


def test_k_prestart_updates_with_new_line():
    row = _k_row()
    _run_k([_pitcher()], row, BEFORE)
    assert row.fanduel_line == 6.5


# ---------- game rows ----------
def _pred(**kw):
    base = dict(
        game_id=11,
        home_team="H",
        away_team="A",
        home_win_prob=0.6,
        away_win_prob=0.4,
        projected_total=9.5,
        game_time="2026-08-05T23:05:00Z",
        ml_recommendation="HOME",
        total_recommendation="NO_PLAY",
        model_confidence=0.2,
        value_rating="No Edge",
    )
    base.update(kw)
    return base


def _game_row(**kw):
    base = dict(
        game_id=11,
        game_time=START,
        home_win_prob=0.55,
        projected_total=8.5,
        market_home_ml=-120,
        market_away_ml=100,
        market_total=8.5,
        market_spread=-1.5,
        edge_vs_market_ml=0.05,
        edge_vs_market_total=0.0,
        ml_recommendation="HOME",
        spread_recommendation="HOME",
        total_recommendation="OVER",
        value_rating="Lean",
        model_confidence=0.5,
        updated_at=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _run_game(pred, row, now):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = row
    with (
        patch.object(gpp, "db_session", session),
        patch.object(gpp, "attach_model_version"),
    ):
        gpp.store_game_projections([pred], DAY, model_version="v", now=now)


def test_game_started_changed_line_is_frozen():
    row = _game_row()
    _run_game(_pred(market_total=9.0, total_recommendation="UNDER"), row, AFTER)
    assert (row.market_total, row.total_recommendation, row.projected_total) == (
        8.5,
        "OVER",
        8.5,
    )


def test_game_started_no_odds_is_frozen():
    row = _game_row()
    _run_game(_pred(), row, AFTER)
    assert row.total_recommendation == "OVER"
    assert row.market_home_ml == -120
    assert row.home_win_prob == 0.55


def test_game_prestart_no_odds_keeps_market_and_recommendations():
    row = _game_row()
    _run_game(_pred(), row, BEFORE)
    assert row.market_total == 8.5 and row.market_home_ml == -120
    assert row.total_recommendation == "OVER"
    assert row.ml_recommendation == "HOME" and row.value_rating == "Lean"
    assert row.home_win_prob == 0.6  # projection itself still refreshes


def test_game_prestart_new_line_updates():
    row = _game_row()
    _run_game(
        _pred(market_total=9.0, edge_vs_market_total=0.5, total_recommendation="UNDER"),
        row,
        BEFORE,
    )
    assert row.market_total == 9.0 and row.total_recommendation == "UNDER"


def test_game_stored_start_wins_over_feed_start():
    # feed now says a later start, but the stored one already passed
    row = _game_row()
    _run_game(_pred(game_time="2026-08-06T01:00:00Z"), row, AFTER)
    assert row.home_win_prob == 0.55


# ---------- odds date filter ----------
def _events(commence):
    return [
        {
            "commence_time": commence,
            "away_team": "A",
            "home_team": "H",
            "bookmakers": [],
        }
    ]


def _fetch(commence, slate):
    resp = MagicMock()
    resp.json.return_value = _events(commence)
    with (
        patch.object(gpp, "ODDS_API_KEY", "k"),
        patch("app.services.odds_api_sync.sync_odds_get", return_value=resp),
    ):
        return gpp.fetch_game_odds(slate)


def test_odds_evening_et_game_after_midnight_utc_is_kept():
    # 20:10 ET Aug 5 == 00:10Z Aug 6
    assert "A @ H" in _fetch("2026-08-06T00:10:00Z", DAY)


def test_odds_next_et_day_game_is_dropped():
    # 00:10 ET Aug 6 early-morning UTC date matches Aug 6 either way
    assert _fetch("2026-08-06T04:10:00Z", DAY) == {}
    # 18:00Z Aug 5 = 14:00 ET Aug 5 is kept
    assert "A @ H" in _fetch("2026-08-05T18:00:00Z", DAY)
