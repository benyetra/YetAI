"""NHL writers stamp best_* on every write (goalie saves, game total) and overwrite it
with None when a rerun finds no consensus; the stored line columns still come from
DraftKings."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import predictions_models as pm
from app.services.etl.nhl import daily_predictions as d
from app.services.etl.nhl import generate_daily_predictions as g
from app.services.etl.nhl.confirm_starters import GoalieStarterContext
from tests.test_consensus_attach_helpers import BEST_KEYS, TOTALS, seed

EVENT = "evt-attach"
SAVES = {
    "draftkings": (24.5, -115, -105),
    "fanduel": (24.5, -110, -110),
    "betmgm": (24.5, -105, -115),  # best over
    "espnbet": (24.5, -120, 100),  # best under
    "williamhill_us": (25.5, 100, -120),
}


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://")
    for t in (
        pm.OddsLineSnapshot,
        pm.NHLGoaliePredictions,
        pm.NHLTeamTotalsPredictions,
    ):
        t.__table__.create(engine)
    s = sessionmaker(bind=engine)()
    monkeypatch.setattr(d, "db_session", s)
    monkeypatch.setattr(d, "find_odds_event", lambda *a, **k: {"id": EVENT})
    yield s
    s.close()


def _game():
    start = datetime.utcnow() + timedelta(hours=4)
    return {
        "id": 1,
        "gameType": 2,
        "startTimeUTC": start.isoformat() + "Z",
        "homeTeam": {"id": 10, "abbrev": "NYR", "placeName": {"default": "New York"}},
        "awayTeam": {"id": 20, "abbrev": "BOS", "placeName": {"default": "Boston"}},
    }


def _totals_run(monkeypatch, db, projection, line=5.5):
    monkeypatch.setattr(
        d,
        "predict_team_total_goals",
        lambda **k: {
            "predicted_home_goals": projection / 2,
            "predicted_away_goals": projection / 2,
            "suggested_ou_line": 5.5,
            "confidence": 0.6,
        },
    )
    monkeypatch.setattr(
        d,
        "enrich_team_totals_prediction_for_write",
        lambda pred, **k: {
            "predicted_total_goals": projection,
            "model_version": "t",
            "features_used": {},
        },
    )
    monkeypatch.setattr(
        g,
        "get_team_totals_odds_for_event",
        lambda *a, **k: {"line": line, "over_odds": -110, "under_odds": -110},
    )
    return d.generate_team_totals_predictions([_game()], [{"id": EVENT}])


def test_team_totals_row_gets_best_then_none_when_stale(db, monkeypatch):
    books = {b: (5.5, a, u) for b, (_, a, u) in SAVES.items()}
    books["williamhill_us"] = (6.5, 100, -120)
    seed(db, books, "totals")
    assert _totals_run(monkeypatch, db, projection=6.3) == 1
    row = db.query(pm.NHLTeamTotalsPredictions).one()
    assert (row.best_side, row.best_line, row.best_book) == ("over", 5.5, "betmgm")
    assert row.best_fair_prob is not None and row.draftkings_ou_line == 5.5
    # rerun with only stale quotes: old price must not survive
    db.query(pm.OddsLineSnapshot).delete()
    db.commit()
    seed(db, books, "totals", age=timedelta(hours=2))
    assert _totals_run(monkeypatch, db, projection=6.3) == 1
    row = db.query(pm.NHLTeamTotalsPredictions).one()
    assert all(getattr(row, k) is None for k in BEST_KEYS)
    assert row.draftkings_ou_line == 5.5


def _slot():
    return GoalieStarterContext(
        game_id=1,
        game_date=datetime.utcnow().date(),
        game_time=None,
        is_home=True,
        team_id=10,
        team_name="New York",
        opponent_team_id=20,
        opponent_team_name="Boston",
        goalie_id=99,
        goalie_name="I. Shesterkin",
        starter_confirmed=True,
        confidence=95,
        should_predict=True,
        prediction_skipped_reason=None,
        method="confirmed",
        full_name="Igor Shesterkin",
    )


def _goalie_run(monkeypatch, saves_line=24.5, predicted=29.0):
    monkeypatch.setattr(
        d,
        "build_slate_starter_context",
        lambda games: SimpleNamespace(slots=[_slot()]),
    )
    monkeypatch.setattr(d, "starter_features_metadata", lambda slot: {})
    monkeypatch.setattr(
        d,
        "predict_goalie_saves",
        lambda **k: {"predicted_saves": predicted, "predicted_shots_against": 31.0},
    )
    monkeypatch.setattr(
        d,
        "enrich_goalie_prediction_for_write",
        lambda pred, meta, saves_line=None: {
            "predicted_saves": predicted,
            "model_version": "t",
            "features_used": {},
        },
    )
    lines = (
        {
            "Igor Shesterkin": {
                "line": saves_line,
                "over_odds": -115,
                "under_odds": -105,
            }
        }
        if saves_line is not None
        else {}
    )
    monkeypatch.setattr(d, "get_goalie_saves_odds_for_event", lambda *a, **k: lines)
    return d.generate_goalie_predictions([_game()], [{"id": EVENT}])


def test_goalie_row_best_is_overwritten_on_rerun(db, monkeypatch):
    seed(db, SAVES, "player_total_saves", player="Igor Shesterkin")
    assert _goalie_run(monkeypatch) == 1
    row = db.query(pm.NHLGoaliePredictions).one()
    assert (row.best_side, row.best_line) == ("over", 24.5)
    assert row.best_book == "betmgm" and row.best_fair_prob is not None
    assert row.saves_line == 24.5 and row.over_odds == -115  # DraftKings, as before
    # rerun: the market gave no line and only stale quotes remain. keep_known keeps the
    # stored line, but best_* are overwritten with None, never left looking current.
    db.query(pm.OddsLineSnapshot).delete()
    db.commit()
    seed(
        db,
        SAVES,
        "player_total_saves",
        player="Igor Shesterkin",
        age=timedelta(hours=2),
    )
    assert _goalie_run(monkeypatch, saves_line=None) == 1
    row = db.query(pm.NHLGoaliePredictions).one()
    assert row.saves_line == 24.5
    assert all(getattr(row, k) is None for k in BEST_KEYS)


def test_goalie_under_side_when_projection_below_line(db, monkeypatch):
    seed(db, SAVES, "player_total_saves", player="Igor Shesterkin")
    _goalie_run(monkeypatch, predicted=20.0)
    row = db.query(pm.NHLGoaliePredictions).one()
    assert (row.best_side, row.best_line, row.best_book) == ("under", 24.5, "espnbet")
