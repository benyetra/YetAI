from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from app.services.etl.wnba import update_expected_minutes as uem


def _game(d: date, minutes: float, *, home: bool | None = True):
    g = MagicMock()
    g.game_date = d
    g.minutes = minutes
    g.home_game = home
    return g


def test_calc_metrics_uses_recency_weights_not_flat_l5():
    today = date(2026, 6, 15)
    # Recent game higher minutes → weighted expected > flat L5
    games = [
        _game(today - timedelta(days=i), 36.0 if i == 0 else 24.0) for i in range(10)
    ]
    metrics = uem._calc_metrics(games)
    assert metrics is not None
    assert metrics["avg_minutes_5"] == 26.4
    assert metrics["expected_base"] > metrics["avg_minutes_5"]


def test_apply_context_b2b_discount():
    today = date(2026, 6, 15)
    metrics = {
        "expected_base": 30.0,
        "last_game_date": today - timedelta(days=1),
        "b2b_minutes_avg": 26.0,
        "home_minutes_avg": None,
        "away_minutes_avg": None,
    }
    adjusted = uem._apply_context_adjustments(metrics, game_date=today, home_game=True)
    assert adjusted == 0.7 * 30.0 + 0.3 * 26.0


def test_expected_minutes_for_player_applies_teammate_boost(monkeypatch):
    db = MagicMock()
    today = date(2026, 6, 15)
    player_games = [_game(today - timedelta(days=i), 28.0) for i in range(6)]

    def query_side(model):
        q = MagicMock()
        name = getattr(model, "__name__", str(model))
        if name == "WNBARecentGames":
            q.filter.return_value.order_by.return_value.limit.return_value.all.return_value = (
                player_games
            )
        elif name == "WNBATeamRoster":
            q.filter_by.return_value.all.return_value = [
                MagicMock(player_id=100, player_name="Bench"),
                MagicMock(player_id=200, player_name="Star"),
            ]
        elif name == "WNBAPlayerInjuryStatus":
            inj = MagicMock(status="out")

            def filter_by(**kwargs):
                fb = MagicMock()
                if kwargs.get("player_id") == 200:
                    fb.first.return_value = inj
                else:
                    fb.first.return_value = None
                return fb

            q.filter_by.side_effect = filter_by
        return q

    db.query.side_effect = query_side

    with patch.object(uem, "_recent_avg_minutes", return_value=32.0):
        mins = uem.expected_minutes_for_player(
            db,
            player_id=100,
            team_id=1,
            game_date=today,
            home_game=True,
            active_by_player={100: 28.0},
        )

    assert mins is not None
    assert mins > 28.0


def test_run_skips_thin_history(monkeypatch):
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr(uem, "SessionLocal", lambda: mock_db)

    active = MagicMock()
    active.player_id = 999
    active.team_id = 1
    active.home_game = True
    mock_db.query.return_value.filter.return_value.all.return_value = [active]

    with patch.object(uem, "_load_recent_games", return_value=[]):
        result = uem.run()

    assert result["status"] == "ok"
    assert result["players_skipped_thin_data"] == 1
    assert active.expected_minutes is None
