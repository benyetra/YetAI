"""Writers stamp best_* (and ml_best_*) on every row they write, None when no consensus,
and leave the legacy line columns as they were. sqlite + seeded snapshots, no network."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import predictions_models as pm
from tests.test_consensus_attach_helpers import (
    BEST_KEYS,
    H2H,
    ML_KEYS,
    SPREADS,
    TOTALS,
    seed,
)

EVENT = "evt-attach"
TABLES = (
    pm.OddsLineSnapshot,
    pm.NBAGameLines,
    pm.NBASpreadActuals,
    pm.NBASpreadProjections,
    pm.NBATotalsProjections,
    pm.TeamDefenseStats,
    pm.TeamOffenseStats,
    pm.NFLGameLines,
    pm.NFLSpreadActuals,
    pm.NFLTeamElo,
    pm.QBPredictions,
    pm.NFLSpreadProjections,
    pm.NFLTotalsProjections,
    pm.RecvYdsPredictions,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    for t in TABLES:
        t.__table__.create(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _model_only(model, market, anchor):
    """With no graded history the anchor publishes the market number itself (edge 0, no
    side); these tests need a projection that differs from the line."""
    return model


def _kept(monkeypatch, module, db):
    """Run a projector against ``db``; capture the upsert rows instead of upserting."""
    rows = []
    monkeypatch.setattr(module, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(
        module, "upsert_many", lambda d, model, r, conflict_keys: rows.extend(r)
    )
    return rows


def _nba_game(db, **kw):
    now = datetime.utcnow()
    g = pm.NBAGameLines(
        game_date=now.date(),
        game_time=now + timedelta(hours=4),
        home_team_id=1,
        away_team_id=2,
        home_team_name="Boston Celtics",
        away_team_name="New York Knicks",
        spread_home=-4.5,
        total=45.5,
        odds_api_event_id=EVENT,
        **kw,
    )
    db.add(g)
    db.commit()


def test_nba_spread_rows_carry_spread_and_moneyline_best(db, monkeypatch):
    from app.services.etl.nba import spread_projector as sp

    _nba_game(db)
    seed(db, SPREADS, "spreads")
    seed(db, H2H, "h2h")
    monkeypatch.setattr(sp, "model_available", lambda: False)
    monkeypatch.setattr(sp, "anchored", _model_only)
    rows = _kept(monkeypatch, sp, db)
    sp.run()
    (row,) = rows
    assert BEST_KEYS | ML_KEYS <= set(row)
    margin = row["projected_margin"]
    expect = "home" if margin - 4.5 > 0 else "away"
    assert row["best_side"] == expect and row["best_fair_prob"] is not None
    assert row["best_line"] == (-4.5 if expect == "home" else 4.5)
    assert row["ml_best_side"] == ("home" if margin > 4.5 else "away")
    assert row["ml_best_fair_prob"] is not None
    assert row["market_spread_home"] == -4.5  # legacy line untouched


def test_nba_spread_rows_none_when_snapshots_are_stale(db, monkeypatch):
    from app.services.etl.nba import spread_projector as sp

    _nba_game(db)
    seed(db, SPREADS, "spreads", age=timedelta(hours=2))
    seed(db, H2H, "h2h", age=timedelta(hours=2))
    monkeypatch.setattr(sp, "model_available", lambda: False)
    rows = _kept(monkeypatch, sp, db)
    sp.run()
    (row,) = rows
    assert all(row[k] is None for k in BEST_KEYS | ML_KEYS)
    assert row["market_spread_home"] == -4.5


def test_nba_totals_save_persists_best_on_insert_and_update(db, monkeypatch):
    from app.services.etl.nba import totals_projector as tp

    monkeypatch.setattr(tp, "db", db, raising=False)
    monkeypatch.setattr(tp, "get_team_id_from_name", lambda n: 1)
    seed(db, TOTALS, "totals")
    best = tp.line_fields(
        db, event_id=EVENT, market="totals", projection=48.0, line=45.5
    )
    assert best["best_side"] == "over"
    base = dict(
        game_date=date.today(),
        home_team="Boston Celtics",
        away_team="New York Knicks",
        projected_total=48.0,
        home_projected_score=24.0,
        away_projected_score=24.0,
        base_projection=48.0,
        expected_pace=99.0,
        home_offensive_rating=110.0,
        away_offensive_rating=110.0,
        home_defensive_rating=110.0,
        away_defensive_rating=110.0,
        injury_adjustment=0.0,
        rest_adjustment=0.0,
        venue_adjustment=0.0,
        form_adjustment=0.0,
        total_adjustment=0.0,
        market_total=45.5,
        edge=2.5,
        recommendation="OVER",
        confidence_score=0.6,
        injury_report={},
        factors={},
    )
    tp.save_projection({**base, "best": best})
    row = db.query(pm.NBATotalsProjections).one()
    assert (row.best_book, row.best_side, row.best_line) == ("betmgm", "over", 45.5)
    # a rerun whose capture was refused overwrites the old price with None
    none = tp.line_fields(
        db, event_id=None, market="totals", projection=48.0, line=45.5
    )
    tp.save_projection({**base, "best": none})
    db.refresh(row)
    assert row.best_book is None and row.best_price is None and row.best_ev is None


def _nfl_game(db):
    now = datetime.utcnow()
    db.add(
        pm.NFLGameLines(
            game_date=(now + timedelta(hours=4)).date(),
            game_time=now + timedelta(hours=4),
            home_team_id=1,
            away_team_id=2,
            home_team_name="Buffalo Bills",
            away_team_name="Miami Dolphins",
            spread_home=-4.5,
            total=45.5,
            odds_api_event_id=EVENT,
        )
    )
    db.commit()


def test_nfl_spread_and_totals_rows_carry_best(db, monkeypatch):
    from app.services.etl.nfl import spread_projector as sp
    from app.services.etl.nfl import totals_projector as tp

    _nfl_game(db)
    seed(db, SPREADS, "spreads")
    seed(db, H2H, "h2h")
    seed(db, TOTALS, "totals")
    monkeypatch.setattr(sp, "anchored", _model_only)
    monkeypatch.setattr(tp, "anchored", _model_only)
    srows = _kept(monkeypatch, sp, db)
    sp.run()
    trows = _kept(monkeypatch, tp, db)
    tp.run()
    (s,), (t,) = srows, trows
    assert BEST_KEYS | ML_KEYS <= set(s)
    assert s["best_side"] in ("home", "away") and s["best_fair_prob"] is not None
    assert s["ml_best_side"] in ("home", "away") and s["ml_best_fair_prob"]
    assert BEST_KEYS <= set(t)
    over = t["projected_total"] > 45.5
    assert t["best_side"] == ("over" if over else "under")
    assert t["best_line"] == 45.5 and t["best_fair_prob"] is not None
    assert t["market_total"] == 45.5


def test_nfl_rows_none_when_snapshots_are_stale(db, monkeypatch):
    from app.services.etl.nfl import spread_projector as sp
    from app.services.etl.nfl import totals_projector as tp

    _nfl_game(db)
    for market, books in (("spreads", SPREADS), ("h2h", H2H), ("totals", TOTALS)):
        seed(db, books, market, age=timedelta(hours=2))
    srows = _kept(monkeypatch, sp, db)
    sp.run()
    trows = _kept(monkeypatch, tp, db)
    tp.run()
    assert all(srows[0][k] is None for k in BEST_KEYS | ML_KEYS)
    assert all(trows[0][k] is None for k in BEST_KEYS)


def _recv_row(db, day, **kw):
    row = pm.RecvYdsPredictions(
        season=2026,
        week=12,
        game_date=day,
        player_id="p1",
        player_name="Tyreek Hill",
        position="WR",
        team_name="Buffalo Bills",
        opponent_team_name="Miami Dolphins",
        predicted_receiving_yards=80.0,
        ou_line=70.5,
        **kw,
    )
    db.add(row)
    db.commit()
    return row


def test_recv_best_quotes_attach_overwrite_and_freeze(db):
    from app.services.etl.nfl.recv_yds_weekly import attach_best_quotes

    day = (datetime.utcnow() + timedelta(hours=4)).date()
    _nfl_game(db)
    props = {
        b: (70.5, a, u) for b, (_, a, u) in TOTALS.items() if b != "williamhill_us"
    }
    props["williamhill_us"] = (75.5, 100, -120)
    seed(db, props, "player_reception_yds", player="Tyreek Hill")
    row = _recv_row(db, day)
    feats = [
        {"season": 2026, "week": 12, "player_id": "p1", "player_name": "Tyreek Hill"}
    ]
    lines = {"Tyreek Hill": {"FanDuel": {"over": {"line": 70.5, "odds": -110}}}}
    assert attach_best_quotes(db, feats, lines) == 1
    db.commit()
    db.refresh(row)
    assert row.best_side == "over" and row.best_line == 70.5
    assert row.best_book == "betmgm" and row.best_fair_prob is not None
    assert row.ou_line == 70.5  # legacy column untouched
    # no player match -> row not rewritten
    assert attach_best_quotes(db, feats, {"Someone Else": lines["Tyreek Hill"]}) == 0
    # capture refused / stale: the old price is overwritten with None
    db.query(pm.OddsLineSnapshot).delete()
    db.commit()
    seed(
        db, props, "player_reception_yds", player="Tyreek Hill", age=timedelta(hours=2)
    )
    attach_best_quotes(db, feats, lines)
    db.commit()
    db.refresh(row)
    assert row.best_book is None and row.best_price is None
    # a game that has kicked off stays frozen
    row.best_book = "old"
    row.game_date = date.today() - timedelta(days=2)
    db.commit()
    assert attach_best_quotes(db, feats, lines) == 0
    db.refresh(row)
    assert row.best_book == "old"


def test_qb_betting_attaches_best_and_keeps_legacy_columns(db, monkeypatch):
    from app.services.etl.nfl import qb_betting as m
    from app.services.etl.nfl import qb_passing_yards_ml as ml

    day = (datetime.utcnow() + timedelta(hours=4)).date()
    _nfl_game(db)
    props = {
        b: (250.5, a, u) for b, (_, a, u) in TOTALS.items() if b != "williamhill_us"
    }
    props["williamhill_us"] = (260.5, 100, -120)
    seed(db, props, "player_pass_yds", player="Josh Allen")
    qb = pm.QBPredictions(
        season=2026,
        week=12,
        qb_player_id="qb1",
        qb_player_name="Josh Allen",
        team_id=1,
        team_name="Buffalo Bills",
        opponent_team_name="Miami Dolphins",
        game_date=datetime.combine(day, datetime.min.time()),
        venue_name="Highmark",
        predicted_passing_yards=300.0,
        model_confidence=0.9,
    )
    db.add(qb)
    db.commit()
    lines = {
        "FanDuel": {
            "over": {"line": 250.5, "odds": -110},
            "under": {"line": 250.5, "odds": -110},
        }
    }
    monkeypatch.setattr(m, "db_session", db)
    monkeypatch.setattr(m, "get_nfl_season", lambda: 2026)
    monkeypatch.setattr(m, "get_current_nfl_week", lambda s: 12)
    monkeypatch.setattr(m, "has_kicked_off", lambda k: False)
    monkeypatch.setattr(m, "get_nfl_games_and_lines", lambda: {"Josh Allen": lines})
    monkeypatch.setattr(ml, "qb_ml_enabled", lambda: False)
    m._run_qb_betting_core()
    db.refresh(qb)
    assert qb.ou_line == 250.5 and qb.best_over_book == "FanDuel"  # legacy
    assert qb.best_side == "over" and qb.best_line == 250.5
    assert qb.best_book == "betmgm" and qb.best_fair_prob is not None
