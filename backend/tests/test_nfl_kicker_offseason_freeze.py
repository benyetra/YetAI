"""Kickers: no off-season rows, no call side, rows frozen at kickoff."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models.predictions_models import KickerPredictions, Kickers
from app.services.etl.nfl import kickers
from app.services.etl.nfl.nfl_common import now_eastern_naive


def _run_with_next_game(monkeypatch, kickoff_utc: datetime):
    """Run the kicker job for one kicker whose next game kicks off at ``kickoff_utc``."""
    event = {
        "date": kickoff_utc.strftime("%Y-%m-%dT%H:%MZ"),
        "competitions": [{"competitors": []}],
    }
    processed = []
    monkeypatch.setattr(
        kickers, "get_all_starting_kickers", lambda: [{"name": "K", "team_id": 1}]
    )
    monkeypatch.setattr(kickers, "get_nfl_teams", lambda: [{"id": 1, "name": "T"}])
    monkeypatch.setattr(kickers, "get_team_schedule", lambda _t: {"events": [event]})
    monkeypatch.setattr(
        kickers, "process_kicker_data", lambda *a, **k: processed.append(a)
    )
    kickers._run_kickers_core()
    return processed


def test_offseason_run_writes_no_rows(monkeypatch):
    # February: ESPN already lists a September game; nothing may be projected.
    far = datetime.utcnow() + timedelta(days=200)
    assert _run_with_next_game(monkeypatch, far) == []


def test_in_season_run_still_writes(monkeypatch):
    soon = datetime.utcnow() + timedelta(days=3)
    assert len(_run_with_next_game(monkeypatch, soon)) == 1


def test_unreadable_kickoff_writes_no_row(monkeypatch):
    monkeypatch.setattr(kickers, "event_kickoff_eastern", lambda _e: None)
    assert _run_with_next_game(monkeypatch, datetime.utcnow()) == []


def test_kicker_rows_carry_no_call_side():
    # Projection rows hold numbers only: nothing for a pick, side or line.
    for model in (Kickers, KickerPredictions):
        cols = {c.name for c in model.__table__.columns}
        assert not {
            c
            for c in cols
            if any(w in c for w in ("recommend", "pick", "over_under", "line", "side"))
        }, cols


def test_started_game_is_never_rewritten(monkeypatch):
    called = []
    monkeypatch.setattr(kickers, "db_session", _Boom(called))
    kickers.save_kicker_data(
        {
            "player_id": 1,
            "name": "K",
            "game_time": now_eastern_naive() - timedelta(hours=2),  # naive = Eastern
        }
    )
    assert called == []


class _Boom:
    def __init__(self, called):
        self._called = called

    def __getattr__(self, name):
        self._called.append(name)
        raise AssertionError(f"db touched: {name}")
