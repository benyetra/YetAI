from datetime import date
from unittest.mock import MagicMock, patch

from app.services.etl.nba import spread_projector as nsp


def test_run_writes_projection(monkeypatch):
    mock_db = MagicMock(name="Session")
    game = MagicMock()
    game.game_date = date(2026, 5, 21)
    game.home_team_id = 1
    game.away_team_id = 2
    game.home_team_name = "Boston Celtics"
    game.away_team_name = "New York Knicks"
    game.spread_home = -4.5

    mock_db.query.return_value.order_by.return_value.all.return_value = []
    mock_db.query.return_value.all.return_value = []
    mock_db.query.return_value.filter.return_value.all.return_value = [game]

    monkeypatch.setattr(
        "app.services.etl.nba.spread_projector.SessionLocal", lambda: mock_db
    )
    monkeypatch.setattr(
        "app.services.etl.nba.spread_projector._load_elos",
        lambda db: {"Boston Celtics": 1520.0, "New York Knicks": 1480.0},
    )

    with patch("app.services.etl.nba.spread_projector.upsert_many") as um:
        result = nsp.run()

    assert result["status"] == "ok"
    assert result["games"] == 1
    row = um.call_args[0][2][0]
    assert row["factors"]["method"] == "elo_pace"
    assert "elo_pace_margin" in row["factors"]
    assert row["market_spread_home"] == -4.5


def test_run_uses_ml_when_model_available(monkeypatch):
    mock_db = MagicMock(name="Session")
    game = MagicMock()
    game.game_date = date(2026, 5, 21)
    game.home_team_id = 1
    game.away_team_id = 2
    game.home_team_name = "Boston Celtics"
    game.away_team_name = "New York Knicks"
    game.spread_home = -4.5
    game.total = 220.5

    mock_db.query.return_value.order_by.return_value.all.return_value = []
    mock_db.query.return_value.all.return_value = []
    mock_db.query.return_value.filter.return_value.all.return_value = [game]

    monkeypatch.setattr(
        "app.services.etl.nba.spread_projector.SessionLocal", lambda: mock_db
    )
    monkeypatch.setattr(
        "app.services.etl.nba.spread_projector._load_elos",
        lambda db: {"Boston Celtics": 1520.0, "New York Knicks": 1480.0},
    )
    monkeypatch.setattr(
        "app.services.etl.nba.spread_projector.model_available", lambda: True
    )
    monkeypatch.setattr(
        "app.services.etl.nba.spread_projector.build_game_features",
        lambda *a, **k: {"elo_diff": 40.0},
    )
    monkeypatch.setattr(
        "app.services.etl.nba.spread_projector.predict_margin", lambda feats: 7.5
    )

    with patch("app.services.etl.nba.spread_projector.upsert_many") as um:
        result = nsp.run()

    assert result["projection_method"] == "ml"
    row = um.call_args[0][2][0]
    assert row["factors"]["method"] == "ml"
    assert row["projected_margin"] == 7.5
