"""scripts/nba_season_rollover_repair.py rebuild-misattributed."""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import PlayerCareerData, RecentGames

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "nba_season_rollover_repair.py"
)


@pytest.fixture
def repair():
    spec = importlib.util.spec_from_file_location("nba_rollover_repair", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    for model in (RecentGames, PlayerCareerData):
        model.__table__.create(engine)
    # Same flags as app.core.database.SessionLocal (autoflush off).
    session = sessionmaker(bind=engine, autoflush=False)()
    yield session
    session.close()


MILLER = 1641706
HOME, AWAY = 5, 2  # API-Sports Hornets, Celtics

GAMES = [
    # Did-not-play game: must be skipped, not stored as "--".
    {"id": 3, "league": "standard", "date": {"start": "2025-12-02T00:00:00.000Z"}},
    # 10:30pm ET Nov 28 == Nov 29 UTC — must land on Nov 28.
    {"id": 1, "league": "standard", "date": {"start": "2025-11-29T03:30:00.000Z"}},
    # 3:30pm ET Nov 29 (same UTC date as the game above).
    {"id": 2, "league": "standard", "date": {"start": "2025-11-29T20:30:00.000Z"}},
]
for g in GAMES:
    g["teams"] = {"home": {"id": HOME}, "visitors": {"id": AWAY}}


def _wire(monkeypatch, repair, *, api_ok=True, stats_ok=True, players=None):
    def fake_api(endpoint, params=None):
        if not api_ok:
            return None
        if endpoint == "seasons":
            return {"response": [2025]}
        if endpoint == "games":
            return {"response": GAMES if params["team"] == HOME else []}
        if endpoint == "players":
            roster = [{"id": 77, "firstname": "Brandon", "lastname": "Miller"}]
            return {"response": roster if params["team"] == HOME else []}
        if endpoint == "players/statistics":
            if not stats_ok:
                return None
            if params["id"] != 77:
                return {"response": []}
            line = {"team": {"id": HOME}, "points": 20, "min": "30"}
            # Game 1 twice (API duplicate) + game 2 + a DNP line ("--").
            return {
                "response": [
                    {**line, "game": {"id": 1}},
                    {**line, "game": {"id": 1}},
                    {**line, "game": {"id": 2}, "points": 31},
                    {**line, "game": {"id": 3}, "min": "--", "points": "--"},
                ]
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(repair, "api_request", fake_api)
    monkeypatch.setattr(
        repair, "affected_players", lambda: players or {MILLER: "Brandon Miller"}
    )
    # Name search finds nobody: ids must come from the team rosters.
    monkeypatch.setattr(repair, "_find_api_player_id", lambda name, pid=None: None)
    monkeypatch.setattr(repair, "run_career_data", lambda **kw: {"status": "ok"})
    monkeypatch.setattr(repair.time, "sleep", lambda s: None)


def test_rebuild_uses_eastern_dates_and_dedupes(monkeypatch, repair, db):
    db.add(
        RecentGames(player_id=MILLER, game_date=date(2025, 1, 1), opponent_team_id=1)
    )
    db.commit()
    _wire(monkeypatch, repair)

    assert repair.cmd_rebuild(db, [2025], apply=True) == 0

    rows = {
        r.game_date: r.points
        for r in db.query(RecentGames).filter_by(player_id=MILLER).all()
    }
    assert rows == {date(2025, 11, 28): 20, date(2025, 11, 29): 31}


def test_rebuild_changes_nothing_when_api_fails(monkeypatch, repair, db, capsys):
    db.add(
        RecentGames(player_id=MILLER, game_date=date(2025, 1, 1), opponent_team_id=1)
    )
    db.commit()
    _wire(monkeypatch, repair, api_ok=False)

    assert repair.cmd_rebuild(db, [2025], apply=True) == 1
    assert db.query(RecentGames).filter_by(player_id=MILLER).count() == 1
    assert "Nothing changed" in capsys.readouterr().out


def test_rebuild_is_rerunnable(monkeypatch, repair, db):
    _wire(monkeypatch, repair)
    assert repair.cmd_rebuild(db, [2025], apply=True) == 0
    assert repair.cmd_rebuild(db, [2025], apply=True) == 0
    assert db.query(RecentGames).filter_by(player_id=MILLER).count() == 2


def test_rebuild_skips_players_unknown_to_api_sports(monkeypatch, repair, db, capsys):
    rupert = 1641712
    db.add(
        RecentGames(player_id=rupert, game_date=date(2025, 1, 1), opponent_team_id=1)
    )
    db.commit()
    _wire(
        monkeypatch, repair, players={MILLER: "Brandon Miller", rupert: "Rayan Rupert"}
    )

    assert repair.cmd_rebuild(db, [2025], apply=True) == 0

    assert db.query(RecentGames).filter_by(player_id=MILLER).count() == 2
    assert db.query(RecentGames).filter_by(player_id=rupert).count() == 0
    assert "Rayan Rupert (2025)" in capsys.readouterr().out


def test_rebuild_aborts_when_a_stats_fetch_fails(monkeypatch, repair, db):
    db.add(
        RecentGames(player_id=MILLER, game_date=date(2025, 1, 1), opponent_team_id=1)
    )
    db.commit()
    _wire(monkeypatch, repair, stats_ok=False)

    assert repair.cmd_rebuild(db, [2025], apply=True) == 1
    assert db.query(RecentGames).filter_by(player_id=MILLER).count() == 1
