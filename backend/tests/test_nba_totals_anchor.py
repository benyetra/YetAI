"""NBA-2/3/6/8: the totals projector publishes the market-anchored total."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

import app.models.database_models  # noqa: F401  (register tables)
from app.core.database import Base
from app.models.predictions_models import (
    NBAGameLines,
    NBASpreadActuals,
    NBATotalsProjections,
    RecentGames,
    TeamRoster,
)
from app.services.etl.nba import totals_ml as tml
from app.services.etl.nba import totals_projector as tp
from app.services.etl.nba.market_anchor import NO_ANCHOR, Anchor, anchored, fit_anchor
from app.services.etl.nba.totals_baseline import (
    ANCHOR_K_PRIOR,
    ANCHOR_A_PRIOR,
    ANCHOR_WINDOW,
    MODEL_VERSION,
    baseline_scores,
    recent_bias,
)

D = date(2026, 11, 14)
HOME, AWAY = "Boston Celtics", "New York Knicks"


@compiles(JSONB, "sqlite")
def _jsonb(type_, compiler, **kw):  # noqa: ARG001
    return "JSON"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tp.db = session
    tp._finals_cache.clear()
    tp._anchor_cache.clear()
    tp.TEAM_NAME_TO_ID.clear()
    tp.TEAM_ID_TO_NAME.clear()
    yield session
    tp.db = None
    tp._finals_cache.clear()
    tp._anchor_cache.clear()
    session.close()
    engine.dispose()


def _final(db, d, home=HOME, away=AWAY, hs=112, as_=108):
    db.add(
        NBASpreadActuals(
            game_date=d,
            home_team_name=home,
            away_team_name=away,
            home_score=hs,
            away_score=as_,
            actual_margin=hs - as_,
            home_won=hs > as_,
        )
    )


def _line(db, d, total, home=HOME, away=AWAY):
    db.add(
        NBAGameLines(game_date=d, home_team_name=home, away_team_name=away, total=total)
    )


def _season(db, n_prior=14, n_cur=14):
    """Prior-season and current-season finals for HOME/AWAY, with lines."""
    for i in range(n_prior):
        d = date(2026, 1, 1) + timedelta(days=3 * i)
        _final(db, d, hs=110 + i % 3, as_=105 + i % 4)
        _line(db, d, 220.0 + i % 5)
    for i in range(n_cur):
        d = date(2026, 10, 22) + timedelta(days=i % 20)
        if i % 2:
            _final(db, d, home=AWAY, away=HOME, hs=108 + i % 5, as_=112)
        else:
            _final(db, d, hs=117 + i % 4, as_=109)
        _line(db, d, 224.5)
    db.commit()


def test_published_total_is_anchored_and_ignores_adjustments(db, monkeypatch):
    _season(db)
    finals = tp.finals_for(D)
    base = sum(baseline_scores(finals, HOME, AWAY, D))
    model = base + recent_bias(finals, D)[0]
    fit = fit_anchor(
        tp.anchor_history(D),
        window=ANCHOR_WINDOW,
        k_prior=ANCHOR_K_PRIOR,
        a_prior=ANCHOR_A_PRIOR,
    )
    assert fit.n > 0
    expected = round(anchored(model, 226.5, fit), 1)
    # Injury, form and venue values must not reach the published number.
    monkeypatch.setattr(tp, "calculate_injury_impact", lambda t, d: (-9.0, []))
    monkeypatch.setattr(tp, "calculate_form_adjustment", lambda h, a, d: 10.0)
    monkeypatch.setattr(tp, "calculate_venue_adjustment", lambda h: 2.5)
    p = tp.generate_projection(HOME, AWAY, D, 226.5)
    assert p["projected_total"] == expected
    assert p["total_adjustment"] == 0.0
    assert p["injury_adjustment"] == -18.0 and p["venue_adjustment"] == 2.5
    assert (
        abs(
            p["home_projected_score"] + p["away_projected_score"] - p["projected_total"]
        )
        <= 0.11
    )
    assert p["factors"]["anchor"]["k"] == round(fit.k, 4)
    assert p["factors"]["anchor"]["n"] == fit.n
    assert p["factors"]["bias_correction"]["source"] == "anchor"
    assert "adjustments_note" in p["factors"]
    assert p["edge"] == round(p["projected_total"] - 226.5, 1)


def test_no_market_publishes_model_total(db):
    _season(db)
    finals = tp.finals_for(D)
    model = sum(baseline_scores(finals, HOME, AWAY, D)) + recent_bias(finals, D)[0]
    p = tp.generate_projection(HOME, AWAY, D, None)
    assert p["projected_total"] == round(model, 1)
    assert p["edge"] is None and p["recommendation"] == "NO_PLAY"


def test_no_baseline_publishes_the_line(db):
    p = tp.generate_projection("Nobody A", "Nobody B", D, 231.5)
    assert p["projected_total"] == 231.5
    assert p["edge"] == 0.0
    assert p["factors"]["anchor"]["n"] == NO_ANCHOR.n


def test_zero_edge_is_stored_as_zero_not_none(db):
    p = tp.generate_projection("Nobody A", "Nobody B", D, 231.5)
    tp.TEAM_NAME_TO_ID["nobody a"] = 1
    tp.save_projection(p)
    row = db.query(NBATotalsProjections).one()
    assert row.edge == 0.0 and row.market_total == 231.5


def test_rest_comes_from_schedule_not_box_scores(db):
    _final(db, D - timedelta(days=1), home=HOME, away="Miami Heat")
    _line(db, D - timedelta(days=2), 220.0, home=AWAY, away="Miami Heat")
    # A stale box-score row dated the day before for an AWAY player: no effect.
    db.add(TeamRoster(team_id=2, player_id=9, player_name="X", last_updated=D))
    db.add(
        RecentGames(player_id=9, game_date=D - timedelta(days=1), opponent_team_id=1)
    )
    db.commit()
    tp.TEAM_NAME_TO_ID["new york knicks"] = 2
    tp.TEAM_NAME_TO_ID["boston celtics"] = 1
    # HOME played yesterday (-2.0); AWAY played 2 days ago, so no penalty.
    assert tp.calculate_rest_adjustment(HOME, AWAY, D) == -2.0
    # Same game, fully rested team (4+ days) adds 0.5.
    assert tp.calculate_rest_adjustment("Miami Heat", "Nobody", D) == -2.0
    assert tp.calculate_rest_adjustment("Nobody", "Nobody 2", D) == 0.0


def test_version_pick_record_counts_only_this_version(db):
    for i in range(3):
        d = D - timedelta(days=10 + i)
        _final(db, d, hs=120, as_=110)  # total 230
        for ver in (MODEL_VERSION, "heuristic-v1", None):
            home = HOME if ver == MODEL_VERSION else f"{HOME} {ver}"
            if ver != MODEL_VERSION:
                _final(db, d, home=home, hs=120, as_=110)
            db.add(
                NBATotalsProjections(
                    game_date=d,
                    home_team_name=home,
                    away_team_name=AWAY,
                    projected_total=230.0,
                    market_total=220.0,
                    model_version=ver,
                )
            )
    db.commit()
    assert tp.version_pick_record(db, D - timedelta(days=30), D) == (3, 3)
    assert tp.version_pick_record(db, D - timedelta(days=11), D) == (2, 2)


def test_unproven_record_withholds_with_note(db, monkeypatch):
    _season(db)
    monkeypatch.setattr(tp, "fit_anchor", lambda *a, **k: Anchor(1.0, 0.0, 50))
    p = tp.generate_projection(HOME, AWAY, D, 190.0)  # huge edge
    assert p["recommendation"] == "NO_PLAY"
    assert "withheld" in p["factors"]["recommendation_note"]


def test_ml_default_path_stamps_anchor_version():
    proj = {"projected_total": 220.0, "market_total": 221.0, "factors": {}}
    assert tml.enrich_projection(proj)["model_version"] == MODEL_VERSION
