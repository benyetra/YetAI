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
async def test_reserve_on_own_pick_gives_up_the_slot(sqlite_db):
    early = NOW + timedelta(hours=2)
    # Only A (late game, best EV) could still be picked at 18:00 ET. The morning run takes
    # A and B itself, so nothing is left for the evening and it takes the full cap now.
    res = await _run(
        sqlite_db,
        [
            _cand(1, commence=LATE, fair=0.56),
            _cand(2, commence=early, fair=0.55),
            _cand(3, commence=early, fair=0.54),
            _cand(4, commence=early, fair=0.53),
        ],
        reserve_slots=1,
    )
    assert sorted(p.candidate.event_id for p in res.picks) == ["e1", "e2", "e3"]
    assert len(_bets(sqlite_db)) == 3


@pytest.mark.asyncio
async def test_same_slate_without_reserve_gives_two(sqlite_db):
    early = NOW + timedelta(hours=2)
    res = await _run(
        sqlite_db, [_cand(1, commence=LATE), _cand(2, 7.25, commence=early)]
    )
    assert res.pick_count == 2
