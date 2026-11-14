"""NBA-1: re-ingesting a game converges to one row per player per game, whatever
date (Eastern D or the legacy UTC D+1) an earlier run filed it under."""

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.predictions_models import Base, RecentGames, TeamRoster
from app.services.etl.nba import update_recent_games as urg

D = date(2026, 11, 9)
D1 = D + timedelta(days=1)
HOME_API, AWAY_API = 1, 2  # API-Sports team ids
TEAM_MAP = {1: 10, 2: 20}


@pytest.fixture
def db(monkeypatch):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def _no_autobegin(conn, _):  # pysqlite: let SAVEPOINT work
        conn.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin(conn):
        conn.exec_driver_sql("BEGIN")

    Base.metadata.create_all(
        engine, tables=[RecentGames.__table__, TeamRoster.__table__]
    )
    session = sessionmaker(bind=engine)()
    monkeypatch.setattr(urg, "SessionLocal", lambda: session)
    monkeypatch.setattr(session, "close", lambda: None)
    monkeypatch.setattr(urg, "is_offseason_date", lambda d: False)
    monkeypatch.setattr(urg, "API_SPORTS_TO_NBA", TEAM_MAP)
    monkeypatch.setattr(urg.time, "sleep", lambda s: None)
    monkeypatch.setattr(urg, "expand_player_name", lambda n, *a: n)
    monkeypatch.setattr(
        urg, "resolve_nba_player_id", lambda name, api_sports_id=None: api_sports_id
    )
    yield session
    session.close()


def _api(monkeypatch, lines, game_id=900, start="2026-11-10T00:30:00Z"):
    """lines: list of (player_api_id, minutes, points, rebounds, assists)."""
    game = {
        "id": game_id,
        "league": "standard",
        "date": {"start": start},
        "teams": {"home": {"id": HOME_API}, "visitors": {"id": AWAY_API}},
    }
    stats = [
        {
            "player": {"id": pid, "firstname": "P", "lastname": str(pid)},
            "team": {"id": HOME_API},
            "min": mins,
            "points": pts,
            "totReb": reb,
            "assists": ast,
        }
        for pid, mins, pts, reb, ast in lines
    ]

    def fake(endpoint, params=None):
        if endpoint == "games":
            return {"response": [game]}
        return {"response": stats}

    monkeypatch.setattr(urg, "api_request", fake)


def _legacy(db, pid, day, opp=20, minutes=30.0, points=20.0, reb=5.0, ast=4.0):
    db.add(
        RecentGames(
            player_id=pid,
            game_date=day,
            opponent_team_id=opp,
            minutes=minutes,
            points=points,
            rebounds=reb,
            assists=ast,
        )
    )
    db.commit()


def _rows(db, pid):
    return db.query(RecentGames).filter_by(player_id=pid).order_by("game_date").all()


def test_legacy_d_plus_1_row_is_moved_to_d(db, monkeypatch):
    _legacy(db, 7, D1)
    _api(monkeypatch, [(7, "30", 20, 5, 4)])
    urg._process_day(D1)
    rows = _rows(db, 7)
    assert [(r.game_date, r.api_game_id) for r in rows] == [(D, 900)]


def test_legacy_pair_d_and_d_plus_1_collapses_to_one(db, monkeypatch):
    _legacy(db, 7, D)
    _legacy(db, 7, D1)
    _api(monkeypatch, [(7, "30", 20, 5, 4)])
    urg._process_day(D1)
    rows = _rows(db, 7)
    assert [(r.game_date, r.api_game_id) for r in rows] == [(D, 900)]


def test_second_run_adds_nothing(db, monkeypatch):
    _api(monkeypatch, [(7, "30", 20, 5, 4), (8, "25", 10, 3, 2)])
    assert urg._process_day(D1) == (2, 0)
    assert urg._process_day(D1) == (0, 2)
    assert db.query(RecentGames).count() == 2


def test_back_to_back_is_not_merged(db, monkeypatch):
    # D+1 row: other opponent, same box -> a different game
    _legacy(db, 7, D1, opp=10)
    # D+1 row: same opponent, different box -> a different game
    _legacy(db, 8, D1, opp=20, points=31.0)
    _api(monkeypatch, [(7, "30", 20, 5, 4), (8, "30", 20, 5, 4)])
    urg._process_day(D1)
    assert len(_rows(db, 7)) == 2
    assert len(_rows(db, 8)) == 2


def test_duplicate_player_api_game_id_rejected(db):
    for _ in range(2):
        db.add(
            RecentGames(
                player_id=1, game_date=D, opponent_team_id=2, **{"api_game_id": 5}
            )
        )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_bad_line_does_not_drop_the_rest_of_the_game(db, monkeypatch):
    _api(monkeypatch, [(7, "30", 20, 5, 4), (8, "25", 10, 3, 2), (9, "20", 8, 1, 1)])
    real = urg.stat_line_fields

    def flaky(ps, h, a):
        if ps["player"]["id"] == 8:
            raise ValueError("bad line")
        return real(ps, h, a)

    monkeypatch.setattr(urg, "stat_line_fields", flaky)
    assert urg._process_day(D1) == (2, 0)
    assert {r.player_id for r in db.query(RecentGames)} == {7, 9}
