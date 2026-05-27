"""Unit tests for cross-league accuracy overview window bounds."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from app.services import (
    mlb_accuracy_service,
    nba_accuracy_service,
    nfl_accuracy_service,
    nhl_accuracy_service,
    wnba_accuracy_service,
)
from app.services.accuracy_overview_service import (
    build_accuracy_overview,
    build_accuracy_overview_diagnostics,
    clear_overview_cache,
    window_date_bounds,
)


def test_window_last_30():
    start, end = window_date_bounds(sport="mlb", mode="last_30", today=date(2026, 6, 1))
    assert end == date(2026, 6, 1)
    assert start == date(2026, 5, 2)


def test_window_mlb_before_opener_rolls_year():
    start, end = window_date_bounds(sport="mlb", mode="season", today=date(2026, 3, 10))
    assert end == date(2026, 3, 10)
    assert start == date(2025, 3, 15)


def test_window_mlb_after_opener_current_year():
    start, end = window_date_bounds(sport="mlb", mode="season", today=date(2026, 7, 1))
    assert start == date(2026, 3, 15)
    assert end == date(2026, 7, 1)


def test_window_nba_before_season_start():
    start, end = window_date_bounds(sport="nba", mode="season", today=date(2026, 9, 15))
    assert start == date(2025, 10, 1)
    assert end == date(2026, 9, 15)


def test_window_wnba():
    start, end = window_date_bounds(sport="wnba", mode="season", today=date(2026, 6, 1))
    assert start == date(2026, 5, 1)
    assert end == date(2026, 6, 1)


def test_build_accuracy_overview_uses_cache(monkeypatch):
    clear_overview_cache()
    calls = {"n": 0}

    def _fake_overview(*_args, **_kwargs):
        calls["n"] += 1
        return {
            "sport": "mlb",
            "label": "MLB",
            "primary": "50%",
            "secondary": "2 graded picks",
            "tone": "warn",
            "has_data": True,
            "graded_count": 2,
        }

    monkeypatch.setattr(mlb_accuracy_service, "season_overview", _fake_overview)
    monkeypatch.setattr(nba_accuracy_service, "season_overview", _fake_overview)
    monkeypatch.setattr(wnba_accuracy_service, "season_overview", _fake_overview)
    monkeypatch.setattr(nfl_accuracy_service, "season_overview", _fake_overview)
    monkeypatch.setattr(nhl_accuracy_service, "season_overview", _fake_overview)

    db = MagicMock()
    first = build_accuracy_overview(db, window="season")
    second = build_accuracy_overview(db, window="season")
    assert first == second
    # 5 leagues computed once, then served from cache.
    assert calls["n"] == 5


def test_build_accuracy_overview_diagnostics_calls_each_league(monkeypatch):
    seen: list[str] = []

    def _fake_diag(db, *, start, end):
        seen.append("x")
        return {"sport": "mock", "parts": []}

    monkeypatch.setattr(mlb_accuracy_service, "season_overview_diagnostics", _fake_diag)
    monkeypatch.setattr(nba_accuracy_service, "season_overview_diagnostics", _fake_diag)
    monkeypatch.setattr(
        wnba_accuracy_service, "season_overview_diagnostics", _fake_diag
    )
    monkeypatch.setattr(nfl_accuracy_service, "season_overview_diagnostics", _fake_diag)
    monkeypatch.setattr(nhl_accuracy_service, "season_overview_diagnostics", _fake_diag)

    db = MagicMock()
    out = build_accuracy_overview_diagnostics(
        db, window="season", today=date(2026, 6, 1)
    )
    assert len(seen) == 5
    assert out["window"] == "season"
    assert out["as_of"] == "2026-06-01"
    assert len(out["leagues"]) == 5
