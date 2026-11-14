"""NBA snapshot freeze: started games, shown lines and sides stay as users saw them."""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import (
    Base,
    NBAGameLines,
    PointsProjections,
    TodayActivePlayers,
)
from app.services.etl import _game_start
from app.services.etl.nba import (
    _stale_rows,
    generate_points_predictions as gpp,
    totals_projector,
    update_game_lines as ugl,
)

TODAY = date(2026, 11, 13)
NOW = datetime(2026, 11, 14, 0, 30, tzinfo=timezone.utc)  # 7:30pm ET
STARTED = datetime(2026, 11, 14, 0, 0)  # naive UTC, 30 min ago
FUTURE = datetime(2026, 11, 14, 2, 0)  # after midnight UTC, still pre-game
HOME, AWAY = "Boston Celtics", "New York Knicks"


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://")
    tables = [
        m.__table__ for m in (NBAGameLines, TodayActivePlayers, PointsProjections)
    ]
    Base.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine)()
    real = _game_start.has_started

    def frozen(start, **kw):
        kw["now"] = NOW  # callers pass now=None; pin the clock
        return real(start, **kw)

    for mod in (_game_start, _stale_rows, ugl):
        monkeypatch.setattr(mod, "has_started", frozen, raising=False)
    monkeypatch.setattr(session, "close", lambda: None)
    yield session
    session.close()


def _game(db, start, spread=-4.5, total=220.5):
    db.add(
        NBAGameLines(
            game_date=TODAY,
            home_team_name=HOME,
            away_team_name=AWAY,
            game_time=start,
            spread_home=spread,
            total=total,
            bookmaker="FanDuel",
        )
    )
    db.commit()


def _player(db, pid=1):
    db.add(
        TodayActivePlayers(
            player_id=pid,
            player_name=f"P{pid}",
            team_id=1,
            team_name=HOME,
            opponent_team_id=2,
            opponent_team_name=AWAY,
            game_date=TODAY,
        )
    )
    db.commit()


def _event(commence, spread=None):
    markets = []
    if spread is not None:
        markets = [
            {
                "key": "spreads",
                "outcomes": [
                    {"name": HOME, "point": spread, "price": -110},
                    {"name": AWAY, "point": -spread, "price": -110},
                ],
            }
        ]
    return {
        "id": "e1",
        "home_team": HOME,
        "away_team": AWAY,
        "commence_time": commence,
        "bookmakers": [{"key": "fanduel", "title": "FanDuel", "markets": markets}],
    }


def _run_lines(monkeypatch, db, event):
    monkeypatch.setattr(ugl, "_fetch_bulk_odds", lambda: [event])
    monkeypatch.setattr(ugl, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        ugl, "now_eastern", lambda: NOW.astimezone(_game_start.EASTERN)
    )
    ugl.run()


# ---- H-1: game lines -------------------------------------------------------


def test_started_game_line_not_rewritten(monkeypatch, db):
    _game(db, STARTED)
    _run_lines(monkeypatch, db, _event("2026-11-14T00:00:00Z", spread=-9.0))
    assert db.query(NBAGameLines).one().spread_home == -4.5


def test_started_game_line_not_nulled_when_book_has_no_market(monkeypatch, db):
    _game(db, STARTED)
    _run_lines(monkeypatch, db, _event("2026-11-14T00:00:00Z"))
    g = db.query(NBAGameLines).one()
    assert (g.spread_home, g.total) == (-4.5, 220.5)


def test_pregame_refresh_with_no_market_keeps_stored_line(monkeypatch, db):
    _game(db, FUTURE)
    _run_lines(monkeypatch, db, _event("2026-11-14T02:00:00Z"))
    g = db.query(NBAGameLines).one()
    assert (g.spread_home, g.total, g.bookmaker) == (-4.5, 220.5, "FanDuel")


def test_pregame_refresh_updates_line(monkeypatch, db):
    _game(db, FUTURE)
    _run_lines(monkeypatch, db, _event("2026-11-14T02:00:00Z", spread=-6.0))
    assert db.query(NBAGameLines).one().spread_home == -6.0


def test_totals_games_exclude_started(monkeypatch, db):
    _game(db, STARTED)
    monkeypatch.setattr(totals_projector, "db", db, raising=False)
    monkeypatch.setattr(totals_projector, "_today", lambda: TODAY)
    assert totals_projector.get_todays_games() == []


def test_totals_games_include_pregame_after_midnight_utc(monkeypatch, db):
    _game(db, FUTURE)
    monkeypatch.setattr(totals_projector, "db", db, raising=False)
    monkeypatch.setattr(totals_projector, "_today", lambda: TODAY)
    assert len(totals_projector.get_todays_games()) == 1


# ---- H-1: props / H-13 -----------------------------------------------------


def test_active_players_skip_started_game(db):
    _game(db, STARTED)
    _player(db)
    assert _stale_rows.active_players_not_started(db, TODAY) == []


def test_active_players_without_game_line_use_date_only(db):
    _player(db)
    assert len(_stale_rows.active_players_not_started(db, TODAY)) == 1


def _points_row(db, line=24.5, side="o", price=-115):
    db.add(
        PointsProjections(
            date=TODAY,
            player_id=1,
            player_name="P1",
            projected_points=27.0,
            fanduel_line=line,
            fanduel_over_under=side,
            fanduel_price=price,
        )
    )
    db.commit()


def _run_points(monkeypatch, db, injured=False, fresh_line=None):
    monkeypatch.setattr(gpp, "SessionLocal", lambda: db)
    monkeypatch.setattr(gpp, "now_eastern", lambda: datetime(2026, 11, 13, 19, 30))
    monkeypatch.setattr(gpp, "get_metadata", lambda s: {})
    monkeypatch.setattr(gpp, "_is_injured", lambda d, p: (injured, "Out"))
    monkeypatch.setattr(gpp, "build_points_features", lambda **k: {})
    monkeypatch.setattr(gpp, "predict_points", lambda f: 20.0)
    monkeypatch.setattr(gpp, "maybe_attach_p_over", lambda *a, **k: None)
    monkeypatch.setattr(gpp, "line_diagnostics", lambda: {})
    monkeypatch.setattr(
        "app.services.etl.nba._fanduel_lines.fetch_fanduel_prop_for_player",
        lambda *a, **k: fresh_line or (None, None, None),
    )
    gpp.run()


def test_started_player_row_untouched_even_if_ruled_out(monkeypatch, db):
    _game(db, STARTED)
    _player(db)
    _points_row(db)
    _run_points(monkeypatch, db, injured=True)
    r = db.query(PointsProjections).one()
    assert (r.projected_points, r.fanduel_line, r.fanduel_over_under) == (
        27.0,
        24.5,
        "o",
    )


def test_started_player_row_not_reprojected_or_relined(monkeypatch, db):
    _game(db, STARTED)
    _player(db)
    _points_row(db)
    _run_points(monkeypatch, db, fresh_line=(30.5, "u", -110))
    r = db.query(PointsProjections).one()
    assert (r.projected_points, r.fanduel_line, r.fanduel_over_under) == (
        27.0,
        24.5,
        "o",
    )


def test_pregame_scratch_keeps_row_marked_out(monkeypatch, db):
    _game(db, FUTURE)
    _player(db)
    _points_row(db)
    _run_points(monkeypatch, db, injured=True)
    r = db.query(PointsProjections).one()
    assert (r.projected_points, r.fanduel_line, r.fanduel_price) == (27.0, 24.5, -115)
    assert r.fanduel_over_under == "OUT"


def test_pregame_active_again_without_fresh_line_restores_side(monkeypatch, db):
    _game(db, FUTURE)
    _player(db)
    _points_row(db, side="OUT")
    _run_points(monkeypatch, db)  # projects 20.0 vs stored line 24.5
    r = db.query(PointsProjections).one()
    assert (r.fanduel_line, r.fanduel_over_under) == (24.5, "u")


def test_pregame_no_market_keeps_previous_line(monkeypatch, db):
    _game(db, FUTURE)
    _player(db)
    _points_row(db)
    _run_points(monkeypatch, db)
    r = db.query(PointsProjections).one()
    assert (r.fanduel_line, r.fanduel_price) == (24.5, -115)
    assert r.projected_points == 20.0


def test_mark_out_skips_table_without_side_column(db):
    class NoSide:
        date = player_id = None

    assert _stale_rows.mark_projection_out(db, NoSide, TODAY, 1) is False
