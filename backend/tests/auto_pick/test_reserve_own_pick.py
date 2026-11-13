"""Round 3: morning reserve keyed on a candidate the morning run itself picks."""

from datetime import timedelta
import pytest
from tests.auto_pick.test_orchestrator import (
    NOW,
    LATE,
    _cand,
    _run,
    _bets,
    _env,
)  # noqa: F401


@pytest.mark.asyncio
async def test_reserve_on_own_pick_loses_floor_fill(sqlite_db):
    early = NOW + timedelta(hours=2)
    # A: late game, clears threshold. B: early game, clears only the floor.
    morning = await _run(
        sqlite_db,
        [_cand(1, commence=LATE), _cand(2, 7.25, commence=early)],
        reserve_slots=1,
    )
    evening = await _run(
        sqlite_db,
        [_cand(1, commence=LATE), _cand(2, 7.25, commence=early)],
        now=NOW + timedelta(hours=6, minutes=30),
    )
    total = len(_bets(sqlite_db))
    # Same slate with no reserve publishes 2 (A + floor fill B).
    assert total == 2


@pytest.mark.asyncio
async def test_same_slate_without_reserve_gives_two(sqlite_db):
    early = NOW + timedelta(hours=2)
    res = await _run(
        sqlite_db, [_cand(1, commence=LATE), _cand(2, 7.25, commence=early)]
    )
    assert res.pick_count == 2
