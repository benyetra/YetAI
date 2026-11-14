"""A1: a failing auto-pick read must not poison the shared session (Postgres aborts the
whole transaction on any failed statement), so each catch-and-continue read runs in a
savepoint. SQLite does not abort, so these tests assert the savepoint instead: a write
made inside the failing read is rolled back, and every source query opens one."""

import asyncio
import importlib
import inspect
import pkgutil
from contextlib import contextmanager
from datetime import date, datetime

import pytest

from app.core.database import Base
from app.models.database_models import BetSource, BetType, YetAIBet
from app.services.auto_pick import context_builder as cb
from app.services.auto_pick import record_gate as rg
from app.services.auto_pick import sources as sources_pkg
from app.services.auto_pick.candidate import slate_window_for_date

NOW = datetime(2026, 11, 13, 16, 0)


def _stray_bet(db):
    """A write made mid-read; a savepoint rollback must undo it."""
    db.add(
        YetAIBet(
            id="stray",
            title="t",
            bet_type=BetType.PROP,
            selection="s",
            odds=-110,
            confidence=70,
            status="pending",
            source=BetSource.AUTO,
            sport="basketball_nba",
        )
    )
    db.flush()


def _stray_count(db):
    return db.query(YetAIBet).filter(YetAIBet.id == "stray").count()


def test_failing_projection_loader_is_isolated(sqlite_db, monkeypatch):
    def bad(db, start, end):
        _stray_bet(db)
        raise RuntimeError("loader blew up")

    def good(db, start, end):
        return {("NBA", "total", None): (3, 5)}

    monkeypatch.setattr(rg, "PROJECTION_LOADERS", {"bad": bad, "good": good})
    out = rg.load_projection_records(sqlite_db, NOW)
    assert out == {("NBA", "total", None): (3, 5)}  # later loader still ran
    assert _stray_count(sqlite_db) == 0  # failed loader rolled back on its own
    assert sqlite_db.query(YetAIBet).count() == 0  # session usable afterwards


def test_failing_gate_load_is_isolated_in_context_builder(sqlite_db, monkeypatch):
    def boom(db, now):
        _stray_bet(db)
        raise RuntimeError("gate blew up")

    monkeypatch.setattr(rg, "load_records", boom)
    assert cb._load_records(sqlite_db, NOW) == {}  # gate stays open
    assert _stray_count(sqlite_db) == 0
    assert cb._load_historical_hit_rates(sqlite_db, NOW) == {}  # next query works


def _source_classes():
    out = []
    for m in pkgutil.iter_modules(sources_pkg.__path__):
        mod = importlib.import_module(f"{sources_pkg.__name__}.{m.name}")
        for name, cls in inspect.getmembers(mod, inspect.isclass):
            if cls.__module__ == mod.__name__ and hasattr(
                cls, "get_todays_projections"
            ):
                out.append(cls)
    return out


@pytest.mark.parametrize("cls", _source_classes(), ids=lambda c: c.__name__)
def test_every_source_query_failure_runs_in_a_savepoint(cls, sqlite_db, monkeypatch):
    Base.metadata.drop_all(sqlite_db.get_bind())  # every query now fails
    opened = []
    real = sqlite_db.begin_nested

    @contextmanager
    def spy():
        opened.append(1)
        with real() as sp:
            yield sp

    monkeypatch.setattr(sqlite_db, "begin_nested", spy)
    rows = asyncio.run(
        cls(sqlite_db).get_todays_projections(slate_window_for_date(date(2026, 11, 13)))
    )
    assert rows == []
    assert opened, f"{cls.__name__} swallowed a failed query without a savepoint"
