"""NFL spread/totals: market-anchored numbers, record-gated calls (same scheme as NBA PR #181)."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.predictions_models import (
    NFLGameLines,
    NFLSpreadActuals,
    NFLSpreadProjections,
    NFLTotalsProjections,
)
from app.services.etl import _spread_model as sm
from app.services.etl._spread_model import NFL_CONFIG, margin_to_win_prob
from app.services.etl.nfl import spread_projector as sp
from app.services.etl.nfl import totals_projector as tp
from tests.auto_pick.conftest import sqlite_db  # noqa: F401  (fixture)

TODAY = date(2026, 11, 14)
OPENER = date(2026, 9, 10)


@pytest.fixture
def db(sqlite_db, monkeypatch):  # noqa: F811
    for mod in (sp, tp):
        monkeypatch.setattr(mod, "SessionLocal", lambda: sqlite_db)
        monkeypatch.setattr(mod, "now_eastern", lambda: datetime(2026, 11, 14, 9, 0))
        monkeypatch.setattr(
            mod, "_load_elos", lambda d: {"Home": 1700.0, "Away": 1500.0}
        )
    monkeypatch.setattr(sqlite_db, "close", lambda: None)
    return sqlite_db


def _game(db, spread, total=44.0, when=datetime(2099, 1, 1)):
    db.add(
        NFLGameLines(
            game_date=TODAY,
            home_team_name="Home",
            away_team_name="Away",
            spread_home=spread,
            total=total,
            game_time=when,
        )
    )
    db.commit()


def _past(db, i, model, market, actual, version="old", total=False, factors="m"):
    """Graded game; margin world by default, total world with total=True.
    factors "m": raw model in factors (new rows); None: older row (raw in projected_*).
    """
    d = OPENER + timedelta(days=i % 40)
    h, a = f"H{i}", f"A{i}"
    key = "model_total" if total else "model_margin"
    f = {key: model} if factors == "m" else factors
    if total:
        db.add(
            NFLTotalsProjections(
                game_date=d,
                home_team_name=h,
                away_team_name=a,
                projected_total=model,
                market_total=market,
                model_version=version,
                factors=f,
            )
        )
        hs, as_ = actual // 2 + 1, actual - actual // 2 - 1
    else:
        db.add(
            NFLSpreadProjections(
                game_date=d,
                home_team_name=h,
                away_team_name=a,
                projected_margin=model,
                home_win_prob=0.5,
                market_spread_home=-market,
                model_version=version,
                factors=f,
            )
        )
        hs, as_ = 20 + actual, 20
    db.add(
        NFLSpreadActuals(
            game_date=d,
            home_team_name=h,
            away_team_name=a,
            home_score=hs,
            away_score=as_,
            actual_margin=hs - as_,
            home_won=hs > as_,
        )
    )


def _row(mod, model, table, today=TODAY):
    mod.run()
    return db_one(table, today)


_DB = {}


def db_one(table, today):
    return _DB["db"].query(table).filter(table.game_date == today).one()


@pytest.fixture(autouse=True)
def _remember(db):
    _DB["db"] = db


def test_history_reads_old_and_new_rows(db):
    _past(db, 0, 5.0, 3.0, 4)  # new row
    _past(db, 1, 6.0, 3.0, 4, factors='{"model_margin": 2.5}')  # JSON string
    _past(db, 2, 7.0, 3.0, 4, factors=None)  # old row: raw in projected_margin
    db.commit()
    assert sorted(sp.spread_anchor_history(db, TODAY)) == [
        (2.5, 3.0, 4),
        (5.0, 3.0, 4),
        (7.0, 3.0, 4),
    ]
    _past(db, 10, 50.0, 44.0, 47, total=True)
    _past(db, 11, 48.0, 44.0, 47, total=True, factors=None)
    db.commit()
    assert sorted(tp.totals_anchor_history(db, TODAY)) == [
        (48.0, 44.0, 47),
        (50.0, 44.0, 47),
    ]
    assert sp.spread_anchor_history(db, OPENER) == []


def test_no_model_information_publishes_line_and_no_play(db):
    # Model always 8 over the line, results unrelated: k ~ 0 -> number = line.
    for i in range(80):
        _past(db, i, 11.0, 3.0, 3 + (-1) ** i * 10)
        _past(db, 200 + i, 58.0, 44.0, 44 + (-1) ** i * 10, total=True)
    db.commit()
    _game(db, -3.0, 44.0)
    s = _row(sp, 0, NFLSpreadProjections)
    t = _row(tp, 0, NFLTotalsProjections)
    assert s.factors["anchor"]["k"] < 0.05
    assert s.projected_margin == pytest.approx(3.0, abs=0.5)
    assert abs(s.factors["model_margin"] - 3.0) > 5  # raw model is far off
    assert s.recommendation == "NO_PLAY"
    assert t.projected_total == pytest.approx(44.0, abs=1.0)
    assert t.recommendation == "NO_PLAY"
    assert s.model_version == "nfl-spread-anchor-v1" and len(s.model_version) <= 20
    assert t.model_version == "nfl-totals-anchor-v1" and len(t.model_version) <= 20
    assert "model_total" in t.factors and "recommendation_note" in t.factors


def test_win_prob_comes_from_anchored_margin(db):
    for i in range(60):
        _past(db, i, 11.0, 3.0, 3 + (-1) ** i * 10)
    db.commit()
    _game(db, -3.0)
    s = _row(sp, 0, NFLSpreadProjections)
    f = s.factors
    assert s.home_win_prob == pytest.approx(
        margin_to_win_prob(s.projected_margin, cfg=NFL_CONFIG)
    )
    assert s.home_win_prob != pytest.approx(
        margin_to_win_prob(f["model_margin"], cfg=NFL_CONFIG)
    )
    assert f["market_win_prob"] == pytest.approx(
        margin_to_win_prob(3.0, cfg=NFL_CONFIG)
    )


def test_totals_scores_use_anchored_total_and_margin(db):
    for i in range(60):
        _past(db, i, 11.0, 3.0, 3 + (-1) ** i * 10)
    db.commit()
    _game(db, -3.0)
    s = _row(sp, 0, NFLSpreadProjections)
    t = _row(tp, 0, NFLTotalsProjections)
    assert t.home_projected_score + t.away_projected_score == pytest.approx(
        t.projected_total
    )
    assert t.home_projected_score - t.away_projected_score == pytest.approx(
        s.projected_margin
    )


def test_no_line_publishes_model_no_play(db):
    _game(db, None, None)
    s = _row(sp, 0, NFLSpreadProjections)
    t = _row(tp, 0, NFLTotalsProjections)
    assert s.projected_margin == s.factors["model_margin"]
    assert s.edge is None and s.recommendation == "NO_PLAY"
    assert t.projected_total == t.factors["model_total"]
    assert t.edge is None and t.recommendation == "NO_PLAY"


def _informative(db):
    for i in range(1000, 1150):
        _past(db, i, 9.0, 3.0, 9)
        _past(db, 2000 + i, 52.0, 44.0, 52, total=True)


def test_record_below_min_picks_withholds_call(db):
    _informative(db)
    for i in range(29):  # 29 hits of this version: one short of MIN_PICKS
        _past(db, i, 9.0, 3.0, 9, version=sp.SPREAD_MODEL_VERSION)
    db.commit()
    _game(db, -2.0)
    s = _row(sp, 0, NFLSpreadProjections)
    assert abs(s.edge) >= NFL_CONFIG.edge_threshold
    assert s.factors["pick_record"] == [29, 29]
    assert s.recommendation == "NO_PLAY"
    assert "withheld" in s.factors["recommendation_note"]


def test_qualifying_record_allows_calls(db):
    _informative(db)
    for i in range(35):
        _past(db, i, 9.0, 3.0, 9, version=sp.SPREAD_MODEL_VERSION)
        _past(db, 500 + i, 52.0, 44.0, 52, version=tp.TOTALS_MODEL_VERSION, total=True)
    db.commit()
    _game(db, -2.0, 40.0)
    s = _row(sp, 0, NFLSpreadProjections)
    t = _row(tp, 0, NFLTotalsProjections)
    assert s.factors["pick_record"] == [35, 35] and s.recommendation == "HOME"
    assert t.factors["pick_record"] == [35, 35] and t.recommendation == "OVER"


def test_started_game_is_not_rewritten(db, monkeypatch):
    _game(db, -3.0, when=datetime(2026, 11, 14, 12, 0))  # kicked off 8am ET... passed
    monkeypatch.setattr(
        "app.services.etl._game_start.has_started", lambda *a, **k: True
    )
    sp.run()
    tp.run()
    assert db.query(NFLSpreadProjections).count() == 0
    assert db.query(NFLTotalsProjections).count() == 0


def test_season_boundary_february_is_previous_season():
    assert sm.season_id_for_date(date(2027, 2, 14), cfg=NFL_CONFIG) == 2026
    assert sm.season_id_for_date(date(2026, 9, 10), cfg=NFL_CONFIG) == 2026
    assert sm.season_id_for_date(date(2026, 7, 31), cfg=NFL_CONFIG) == 2025
    assert sp.season_opener(date(2027, 2, 14)) == date(2026, 8, 1)


def test_nfl_logistic_scale_matches_margin_sd():
    # sd of a logistic = scale * pi / sqrt(3); NFL margin sd vs spread ~13.5.
    assert NFL_CONFIG.win_prob_logistic_scale * 3.14159 / 3**0.5 == pytest.approx(
        13.5, abs=0.3
    )
