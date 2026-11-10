from app.services.etl.nfl.collect_recv_yds_actuals import grade_recv_row


def test_grade_recv_row_error_and_ou_hit():
    out = grade_recv_row(actual_yards=90.0, predicted=85.0, ou_line=80.0)
    assert out["prediction_error"] == 5.0
    assert out["hit_over_under"] is True


def test_grade_recv_row_null_line():
    out = grade_recv_row(actual_yards=90.0, predicted=85.0, ou_line=None)
    assert out["hit_over_under"] is None


def test_run_grades_against_this_seasons_week_only(monkeypatch):
    """The usage loader also returns last season; its same-numbered week must
    not be graded as this week's result."""
    from unittest.mock import MagicMock

    from app.services.etl.nfl import _db, collect_recv_yds_actuals as mod
    from app.services.etl.nfl import nfl_common, recv_yds_usage

    captured = {}

    def fake_collect(session, *, season, week, weekly_stats):
        captured.update(season=season, week=week, weekly_stats=weekly_stats)
        return len(weekly_stats)

    monkeypatch.setattr(mod, "collect_for_week", fake_collect)
    monkeypatch.setattr(_db, "init_session", lambda: None)
    monkeypatch.setattr(_db, "close_session", lambda: None)
    monkeypatch.setattr(_db, "db_session", MagicMock())
    monkeypatch.setattr(nfl_common, "get_nfl_season", lambda: 2026)
    monkeypatch.setattr(nfl_common, "get_current_nfl_week", lambda *a, **k: 10)
    monkeypatch.setattr(
        recv_yds_usage,
        "load_weekly_receiver_rows",
        lambda season: [
            {"player_id": "a", "season": 2025, "week": 9, "receiving_yards": 150},
            {"player_id": "a", "season": 2026, "week": 8, "receiving_yards": 20},
            {"player_id": "b", "season": 2026, "week": 9, "receiving_yards": 64},
        ],
    )

    out = mod.run()

    assert out["week"] == 9
    assert captured["weekly_stats"] == [
        {"player_id": "b", "season": 2026, "week": 9, "receiving_yards": 64}
    ]
