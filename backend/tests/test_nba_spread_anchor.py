"""NBA spread projection: market-anchored margin, record-gated calls (NBA-7/NBA-8)."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.predictions_models import (
    NBAGameLines,
    NBASpreadActuals,
    NBASpreadProjections,
)
from app.services.etl._spread_model import NBA_CONFIG, margin_to_win_prob
from app.services.etl.nba import spread_projector as sp
from tests.auto_pick.conftest import sqlite_db  # noqa: F401  (fixture)

TODAY = date(2026, 11, 14)
OPENER = date(2026, 10, 21)


def _row(edge, cover, line=-5.0):
    """Graded row whose model edge is `edge` and result vs the line is `cover`."""
    return SimpleNamespace(
        projected_margin=-line + edge,
        market_spread_home=line,
        actual_margin=-line + cover,
    )


def test_pick_record_counts_hits_and_skips():
    rows = [
        _row(3.0, 2.0),  # hit
        _row(3.0, -2.0),  # miss
        _row(-3.0, -1.0),  # hit (away side)
        _row(1.0, 5.0),  # below threshold
        _row(3.0, 0.0),  # push
        SimpleNamespace(projected_margin=4, market_spread_home=None, actual_margin=3),
        SimpleNamespace(projected_margin=4, market_spread_home=-3, actual_margin=None),
        SimpleNamespace(projected_margin=None, market_spread_home=-3, actual_margin=3),
    ]
    assert sp.spread_pick_record(rows, 2.0) == (2, 3)
    assert sp.spread_pick_record(rows, 3.0) == (2, 3)
    assert sp.spread_pick_record(rows, 3.5) == (0, 0)


@pytest.fixture
def db(sqlite_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(sp, "SessionLocal", lambda: sqlite_db)
    monkeypatch.setattr(sp, "now_eastern", lambda: datetime(2026, 11, 14, 9, 0))
    monkeypatch.setattr(sp, "model_available", lambda: False)
    monkeypatch.setattr(sp, "_load_elos", lambda d: {"Home": 1700.0, "Away": 1500.0})
    monkeypatch.setattr(sqlite_db, "close", lambda: None)
    return sqlite_db


def _game(db, spread):
    db.add(
        NBAGameLines(
            game_date=TODAY,
            home_team_name="Home",
            away_team_name="Away",
            spread_home=spread,
            game_time=datetime(2099, 1, 1),
        )
    )
    db.commit()


def _past(db, i, model, market, actual, version=sp.SPREAD_MODEL_VERSION, factors="m"):
    d = OPENER + timedelta(days=i % 20)
    h, a = f"H{i}", f"A{i}"
    f = {"model_margin": model} if factors == "m" else factors
    db.add(
        NBASpreadProjections(
            game_date=d,
            home_team_name=h,
            away_team_name=a,
            projected_margin=model,
            home_win_prob=0.5,
            market_spread_home=-market,
            edge=model - market,
            model_version=version,
            factors=f,
        )
    )
    db.add(
        NBASpreadActuals(
            game_date=d,
            home_team_name=h,
            away_team_name=a,
            home_score=100 + actual,
            away_score=100,
            actual_margin=actual,
            home_won=actual > 0,
        )
    )


def _informative_history(db):
    """Old-version games where the model's gap to the line predicts the result,
    so the fitted k is large enough for a real edge."""
    for i in range(1000, 1400):
        _past(db, i, 9.0, 3.0, 9, version="old")


def _run(db):
    sp.run()
    return (
        db.query(NBASpreadProjections)
        .filter(NBASpreadProjections.game_date == TODAY)
        .one()
    )


def test_history_reads_model_margin_dict_or_json_and_skips_no_market(db):
    _past(db, 0, 5.0, 3.0, 4)
    _past(db, 1, 6.0, 3.0, 4, factors='{"model_margin": 2.5}')
    _past(db, 2, 7.0, 3.0, 4, factors=None)  # older row: raw model in projected_margin
    _past(db, 3, 7.0, 3.0, 4)
    db.query(NBASpreadProjections).filter(
        NBASpreadProjections.home_team_name == "H3"
    ).update({"market_spread_home": None})
    db.commit()
    got = sp.spread_anchor_history(db, TODAY)
    assert sorted(got) == [(2.5, 3.0, 4), (5.0, 3.0, 4), (7.0, 3.0, 4)]
    assert sp.spread_anchor_history(db, OPENER) == []


def test_published_margin_is_anchored_to_market(db):
    # The model is 3 points above the line yet no better than it: k fitted ~0.
    for i in range(60):
        _past(db, i, 5.0 + (i % 3), 5.0, 5 + (-1) ** i * 8, version="old")
    db.commit()
    _game(db, -4.0)
    row = _run(db)
    f = row.factors
    assert f["anchor"]["n"] == 60 and f["anchor"]["k"] < 0.15
    assert abs(row.projected_margin - 4.0) < abs(f["model_margin"] - 4.0)
    assert f["model_margin"] > 8  # Elo gap 200 -> ~8 + hca
    assert row.projected_margin == pytest.approx(
        4.0 + f["anchor"]["k"] * (f["model_margin"] - 4.0)
    )
    assert row.home_win_prob == pytest.approx(
        margin_to_win_prob(row.projected_margin, cfg=NBA_CONFIG)
    )
    assert f["market_margin"] == 4.0
    assert f["market_win_prob"] == pytest.approx(
        margin_to_win_prob(4.0, cfg=NBA_CONFIG)
    )
    assert row.model_version == sp.SPREAD_MODEL_VERSION
    assert len(row.model_version) <= 20
    for key in ("elo_diff", "pace_adj", "elo_pace_margin", "method", "ml_version"):
        assert key in f
    assert f["pick_record"] == [0, 0]
    assert "recommendation_note" in f


def test_no_market_publishes_model(db):
    _past(db, 0, 5.0, 5.0, 5)
    db.commit()
    _game(db, None)
    row = _run(db)
    f = row.factors
    assert row.projected_margin == f["model_margin"]
    assert f["market_margin"] is None and f["market_win_prob"] is None
    assert row.edge is None and row.recommendation == "NO_PLAY"


def test_unproven_version_withholds_call_even_at_big_edge(db):
    # 29 graded would-be calls of this version, all hits; plus 40 of another version.
    _informative_history(db)
    for i in range(29):
        _past(db, i, 9.0, 3.0, 9)  # model +6 over line, home covers
    for i in range(100, 140):
        _past(db, i, 9.0, 3.0, 9, version="other-v0")
    db.commit()
    _game(db, -2.0)  # market margin 2, model ~10 -> big edge
    row = _run(db)
    assert abs(row.edge) >= NBA_CONFIG.edge_threshold
    assert row.recommendation == "NO_PLAY"
    assert row.factors["pick_record"] == [29, 29]
    assert "withheld" in row.factors["recommendation_note"]
    assert row.confidence_score == 0.5


def test_qualifying_record_allows_call(db):
    _informative_history(db)
    for i in range(35):
        _past(db, i, 9.0, 3.0, 9)
    db.commit()
    _game(db, -2.0)
    row = _run(db)
    assert row.factors["pick_record"] == [35, 35]
    assert row.edge > 0 and row.recommendation == "HOME"
    assert row.confidence_score > 0.5
