"""ATD rows freeze per game at kickoff; no call sides; QB prior; version."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from app.services.etl.nfl import anytime_td_betting as betting
from app.services.etl.nfl import anytime_td_projector as proj
from app.services.etl.nfl.anytime_td_calibration import (
    MODEL_VERSION_GBM,
    MODEL_VERSION_HIER,
)
from app.services.etl.nfl.anytime_td_features import (
    _CONVERSION_RATE_PRIOR,
    _PLAYER_RZ_SHARE_PRIOR,
    _kickoff,
)
from app.services.etl.nfl.anytime_td_model import anytime_td_probability

SUNDAY = date(2026, 11, 15)
NOW = datetime(2026, 11, 15, 15, 30)  # Sunday 15:30 ET


def _feat(pid, hh, mm):
    return {
        "player_id": pid,
        "player_name": pid,
        "position": "WR",
        "team_name": "A",
        "opponent_team_name": "B",
        "game_date": SUNDAY,
        "kickoff": datetime(2026, 11, 15, hh, mm),
        "team_rz_trips": 3.2,
        "player_rz_share": 0.2,
        "conversion_rate": 0.3,
        "defense_mult": 1.0,
        "weather_mult": 1.0,
        "script_mult": 1.0,
    }


def test_run_locks_started_game_but_updates_later_game():
    rows = [_feat("early", 13, 0), _feat("late", 16, 25)]
    with (
        patch.object(proj, "SessionLocal", return_value=MagicMock()),
        patch.object(proj, "_try_build_feature_rows", return_value=rows),
        patch.object(proj, "now_eastern_naive", return_value=NOW),
        patch.object(proj, "upsert_many") as um,
        patch.object(proj, "delete_stale_week_predictions", return_value=0),
    ):
        result = proj.run(season=2026)
    assert result["frozen_played"] == 1
    assert [r["player_id"] for r in um.call_args[0][2]] == ["late"]


def _orm(pid, hh, mm):
    row = MagicMock()
    row.player_id = pid
    row.game_date = SUNDAY
    row.features = {"kickoff": datetime(2026, 11, 15, hh, mm).isoformat()}
    return row


def test_purge_spares_started_game():
    db = MagicMock()
    q = db.query.return_value
    q.filter.return_value = q
    early, late = _orm("early", 13, 0), _orm("late", 16, 25)
    q.all.return_value = [early, late]
    with patch.object(proj, "now_eastern_naive", return_value=NOW):
        n = proj.delete_stale_week_predictions(
            db, season=2026, week=10, keep_player_ids=["x"], on_or_after=SUNDAY
        )
    assert n == 1
    db.delete.assert_called_once_with(late)


def test_betting_refresh_skips_started_game():
    early, late = _orm("early", 13, 0), _orm("late", 16, 25)
    for p in (early, late):
        p.player_name = p.player_id
        p.td_probability = 0.3
        p.model_version = MODEL_VERSION_HIER
        p.market_odds = p.market_implied_prob = p.edge = p.recommendation = None
    db = MagicMock()
    db.query.return_value.filter_by.return_value.all.return_value = [early, late]
    week_patch = patch.object(betting, "get_current_nfl_week", return_value=10)
    with (
        week_patch,
        patch.object(betting, "SessionLocal", return_value=db),
        patch.object(betting, "fetch_anytime_td_odds", return_value={"x": 1}),
        patch.object(betting, "match_player_odds", return_value=None),
        patch.object(betting, "now_eastern_naive", return_value=NOW),
        patch.object(betting, "upsert_many") as um,
    ):
        out = betting.run(season=2026)
    assert out["frozen"] == 1
    assert [r["player_id"] for r in um.call_args[0][2]] == ["late"]


def test_unknown_kickoff_on_past_date_stays_frozen():
    assert proj._is_played(date(2026, 11, 14), {}, NOW)


def test_unknown_kickoff_today_is_started_from_0930_et():
    assert not proj._is_played(SUNDAY, {}, datetime(2026, 11, 15, 9, 29))
    assert proj._is_played(SUNDAY, {}, datetime(2026, 11, 15, 9, 30))
    assert not proj._is_played(date(2026, 11, 16), {}, NOW)  # tomorrow


def test_stored_row_kickoff_freezes_a_new_row_without_one():
    stored = {"kickoff": datetime(2026, 11, 15, 13, 0).isoformat()}
    assert proj._is_played(SUNDAY, {}, NOW, stored)
    later = {"kickoff": datetime(2026, 11, 15, 16, 25).isoformat()}
    assert not proj._is_played(SUNDAY, {}, NOW, later)
    # the new row's own kickoff counts too
    assert proj._is_played(SUNDAY, stored, NOW, later)


def test_run_keeps_stored_started_row_when_new_row_lost_its_kickoff():
    row = {**_feat("early", 13, 0), "kickoff": None}
    stored = {"early": {"kickoff": datetime(2026, 11, 15, 13, 0).isoformat()}}
    with (
        patch.object(proj, "SessionLocal", return_value=MagicMock()),
        patch.object(proj, "_try_build_feature_rows", return_value=[row]),
        patch.object(proj, "_stored_features", return_value=stored),
        patch.object(proj, "now_eastern_naive", return_value=NOW),
        patch.object(proj, "upsert_many") as um,
        patch.object(proj, "delete_stale_week_predictions", return_value=0),
    ):
        result = proj.run(season=2026)
    assert result["frozen_played"] == 1
    um.assert_not_called()


def test_kickoff_parsed_from_gametime():
    assert _kickoff(SUNDAY, "13:00") == datetime(2026, 11, 15, 13, 0)
    assert _kickoff(SUNDAY, float("nan")) is None
    assert _kickoff(None, "13:00") is None


def test_attach_never_calls_a_side():
    out = betting.attach_betting_fields(
        td_probability=0.9, market_odds=+400, features={"p_model": 0.9}
    )
    assert out["recommendation"] == "NO_PLAY"
    assert out["edge"] is not None


def test_qb_prior_matches_backtest_prior():
    lam = 3.2 * _PLAYER_RZ_SHARE_PRIOR["QB"] * _CONVERSION_RATE_PRIOR["QB"]
    assert abs(anytime_td_probability(lam) - 0.12) < 0.01


def test_model_version_bumped_and_fits_column():
    assert MODEL_VERSION_HIER == "hierarchical_v2"
    assert len(MODEL_VERSION_GBM + "_mkt") <= 64
