"""
Tests for AutoPickOrchestrator (SQLite-backed, fake providers).

Slate: 2026-05-22 ET. ``NOW`` is 11:00 ET = 15:00 UTC.
"""

import json
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.models.database_models import (
    AutoPickRun,
    AutoPickRunStatus,
    BetSource,
    BetType,
    YetAIBet,
)
from app.services.auto_pick import orchestrator as orch_mod
from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.orchestrator import AutoPickOrchestrator

NOW = datetime(2026, 5, 22, 15, 0)
SLATE = date(2026, 5, 22)
LATE = NOW + timedelta(hours=10)  # later games for top-up runs
LEAGUES = ("NBA", "WNBA", "NFL", "MLB")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in (
        "AUTO_YETAI_PICKS_AUTO_PUBLISH",
        "AUTO_YETAI_PARLAY_ENABLED",
        "AUTO_YETAI_PICKS_MIN_SCORE",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(orch_mod, "_can_grade", lambda league, market, stat: True)


def _cand(
    n: int,
    projection: float = 9.0,
    side: str | None = "over",
    commence: datetime | None = NOW + timedelta(hours=4),
    selection: str | None = None,
    game: int | None = None,
    **kw,
) -> BetCandidate:
    """Prop candidate in its own game. projection 9.0 vs line 5.5 -> max edge.

    League rotates with the game so the per-market cap (2) does not bind by default.
    """
    g = n if game is None else game
    kw.setdefault("league", LEAGUES[(g - 1) % len(LEAGUES)])
    md = {
        "sample_size": 30,
        "model_confidence": 0.78,
        "side": side,
        "stat": "points",
        "player": f"Player {n}",
    }
    return BetCandidate(
        market_type=MarketType.PLAYER_PROP,
        event_id=f"e{n}",
        selection=selection or f"Player {n} OVER 5.5 points",
        market_line=5.5,
        market_odds=-110,
        our_projection=projection,
        projection_metadata=md,
        home_team=f"Home {g}",
        away_team=f"Away {g}",
        commence_time=commence,
        game_date=SLATE,
        **kw,
    )


def _provider(cands):
    p = AsyncMock()
    p.get_candidates = AsyncMock(return_value=cands)
    return p


async def _run(db, cands, now=NOW, **kw):
    return await AutoPickOrchestrator(
        db=db, providers=[_provider(cands)], now=now, **kw
    ).run()


def _bets(db):
    return db.query(YetAIBet).order_by(YetAIBet.created_at, YetAIBet.id).all()


def _counts(db):
    return db.query(AutoPickRun).one().dropped_reasons["counts"]


def _counts_last(db):
    run = db.query(AutoPickRun).order_by(AutoPickRun.id.desc()).first()
    return run.dropped_reasons["counts"]


@pytest.mark.asyncio
async def test_publishes_active_with_grading_block(sqlite_db):
    result = await _run(sqlite_db, [_cand(1)])

    assert result.status == AutoPickRunStatus.SUCCESS and result.pick_count == 1
    (bet,) = _bets(sqlite_db)
    assert bet.status == "active" and bet.source == BetSource.AUTO
    assert bet.auto_pick_run_id == result.id
    assert bet.prediction_factors["grading"] == {
        "market": "player_prop",
        "league": "NBA",
        "game_date": "2026-05-22",
        "home_team": "Home 1",
        "away_team": "Away 1",
        "side": "over",
        "line": 5.5,
        "player": "Player 1",
        "stat": "points",
    }
    assert bet.prediction_factors["slate_date"] == "2026-05-22"
    assert bet.prediction_factors["event_id"] == "e1"


@pytest.mark.asyncio
async def test_grading_block_for_game_markets_has_no_player(sqlite_db):
    c = _cand(1)
    c.market_type = MarketType.MONEYLINE
    c.market_line = 0.0
    c.our_projection = 0.8
    c.projection_metadata = {"side": "home", "opp_odds": 120, "model_confidence": 0.8}
    await _run(sqlite_db, [c])
    g = _bets(sqlite_db)[0].prediction_factors["grading"]
    assert g["market"] == "moneyline" and g["line"] is None
    assert "player" not in g and "stat" not in g


@pytest.mark.asyncio
async def test_second_run_with_three_published_adds_nothing(sqlite_db):
    cands = [_cand(i) for i in range(1, 5)]
    await _run(sqlite_db, cands)
    assert len(_bets(sqlite_db)) == 3

    later = await _run(
        sqlite_db,
        [_cand(i, commence=LATE) for i in range(5, 8)],
        now=NOW + timedelta(hours=6),
    )
    assert later.pick_count == 0
    assert _counts_last(sqlite_db) == {"cap_reached": 3}
    assert len(_bets(sqlite_db)) == 3


@pytest.mark.asyncio
async def test_with_two_published_adds_exactly_one_and_leaves_earlier_rows(sqlite_db):
    await _run(sqlite_db, [_cand(1), _cand(2)])
    before = {
        b.id: (b.status, b.selection, b.confidence_score, b.tier_requirement)
        for b in _bets(sqlite_db)
    }
    assert len(before) == 2

    later = await _run(
        sqlite_db,
        [
            _cand(1, commence=LATE),
            _cand(2, commence=LATE),
            _cand(3, commence=LATE),
            _cand(4, commence=LATE),
        ],
        now=NOW + timedelta(hours=6),
    )

    assert later.pick_count == 1
    rows = _bets(sqlite_db)
    assert len(rows) == 3
    for b in rows:
        if b.id in before:
            assert (
                b.status,
                b.selection,
                b.confidence_score,
                b.tier_requirement,
            ) == before[b.id]
    # Re-presented games 1 and 2 were dropped as already used.
    assert _counts_last(sqlite_db)["event_already_used"] == 2


@pytest.mark.asyncio
async def test_never_duplicates_a_game_within_or_across_runs(sqlite_db):
    same_game = [
        _cand(1, selection="Player 1 OVER 5.5 points"),
        _cand(2, selection="Player 2 OVER 5.5 points", game=1),
    ]
    await _run(sqlite_db, same_game)
    assert len(_bets(sqlite_db)) == 1

    await _run(
        sqlite_db,
        [_cand(3, game=1, selection="Other pick", commence=LATE)],
        now=NOW + timedelta(hours=6),
    )
    assert len(_bets(sqlite_db)) == 1


@pytest.mark.asyncio
async def test_rejected_and_pending_rows_do_not_use_slots(sqlite_db):
    for i, status in enumerate(("rejected", "pending_approval")):
        sqlite_db.add(
            YetAIBet(
                id=f"old{i}",
                title="t",
                bet_type=BetType.PROP,
                selection="s",
                odds=-110.0,
                confidence=70.0,
                status=status,
                source=BetSource.AUTO,
                created_at=NOW - timedelta(hours=1),
                prediction_factors={"event_id": "zzz"},
            )
        )
    sqlite_db.commit()
    await _run(sqlite_db, [_cand(i) for i in range(1, 5)])
    assert sum(1 for b in _bets(sqlite_db) if b.status == "active") == 3


@pytest.mark.asyncio
async def test_void_row_frees_its_slot_but_not_its_game(sqlite_db):
    await _run(sqlite_db, [_cand(i) for i in range(1, 5)])
    rows = _bets(sqlite_db)
    assert len(rows) == 3
    rows[0].status = "void"  # admin pulled it
    sqlite_db.commit()
    voided_game = rows[0].home_team

    later = await _run(
        sqlite_db,
        [_cand(1, commence=LATE), _cand(5, commence=LATE), _cand(6, commence=LATE)],
        now=NOW + timedelta(hours=6),
    )
    assert later.pick_count == 1
    new = [b for b in _bets(sqlite_db) if b.id not in {r.id for r in rows}]
    assert len(new) == 1 and new[0].home_team != voided_game
    assert sum(1 for b in _bets(sqlite_db) if b.status != "void") == 3


@pytest.mark.asyncio
async def test_yesterdays_slate_does_not_count(sqlite_db):
    sqlite_db.add(
        YetAIBet(
            id="y",
            title="t",
            bet_type=BetType.PROP,
            selection="s",
            odds=-110.0,
            confidence=70.0,
            status="active",
            source=BetSource.AUTO,
            created_at=datetime(2026, 5, 21, 20, 0),
            prediction_factors={"event_id": "zzz"},
        )
    )
    sqlite_db.commit()
    result = await _run(sqlite_db, [_cand(i) for i in range(1, 5)])
    assert result.pick_count == 3


@pytest.mark.asyncio
async def test_fill_to_two_from_floor(sqlite_db):
    # 9.0 -> ~82 (threshold); 7.25 -> ~60 (floor only); 7.1 -> ~58; 6.0 -> ~52
    cands = [_cand(1), _cand(2, 7.25), _cand(3, 7.1), _cand(4, 6.0)]
    result = await _run(sqlite_db, cands)
    assert result.pick_count == 2
    assert sorted(b.selection for b in _bets(sqlite_db)) == [
        "Player 1 OVER 5.5 points",
        "Player 2 OVER 5.5 points",
    ]
    counts = _counts(sqlite_db)
    assert counts["below_threshold"] == 1 and counts["below_floor"] == 1


@pytest.mark.asyncio
async def test_zero_picks_when_nothing_clears_floor(sqlite_db):
    result = await _run(sqlite_db, [_cand(1, 6.0), _cand(2, 5.9)])
    assert result.status == AutoPickRunStatus.NO_PICKS and result.pick_count == 0
    assert _bets(sqlite_db) == []
    assert _counts(sqlite_db) == {"below_floor": 2}


@pytest.mark.asyncio
async def test_started_or_starting_game_dropped(sqlite_db):
    cands = [
        _cand(1, commence=NOW - timedelta(minutes=30)),
        _cand(2, commence=NOW + timedelta(minutes=10)),
    ]
    result = await _run(sqlite_db, cands)
    assert result.pick_count == 0
    assert _counts(sqlite_db) == {"started_or_starting": 2}


@pytest.mark.asyncio
async def test_ungradeable_dropped(sqlite_db, monkeypatch):
    seen = []

    def fake(league, market, stat):
        seen.append((league, market, stat))
        return False

    monkeypatch.setattr(orch_mod, "_can_grade", fake)
    result = await _run(sqlite_db, [_cand(1)])
    assert result.pick_count == 0
    assert _counts(sqlite_db) == {"ungradeable": 1}
    assert seen == [("NBA", "player_prop", "points")]


@pytest.mark.asyncio
async def test_missing_side_is_no_play(sqlite_db):
    result = await _run(sqlite_db, [_cand(1, side=None)])
    assert result.pick_count == 0
    assert _counts(sqlite_db) == {"no_play": 1}


@pytest.mark.asyncio
async def test_non_positive_edge_and_injury_dropped(sqlite_db):
    inj = _cand(2)
    inj.projection_metadata["injury_flag"] = True
    await _run(sqlite_db, [_cand(1, projection=5.0), inj])
    assert _counts(sqlite_db) == {"non_positive_edge": 1, "injury_flag": 1}


@pytest.mark.asyncio
async def test_dropped_reasons_keep_every_candidate_of_a_game(sqlite_db):
    cands = [_cand(1, 6.0), _cand(2, 5.9, game=1)]  # same game, both below floor
    await _run(sqlite_db, cands)
    run = sqlite_db.query(AutoPickRun).one()
    assert run.dropped_reasons["counts"] == {"below_floor": 2}
    top = run.dropped_reasons["top_rejected"]
    assert [t["event_id"] for t in top] == ["e1", "e2"]  # sorted by score desc
    assert set(top[0]) == {
        "event_id",
        "selection",
        "league",
        "market",
        "score",
        "reason",
    }


@pytest.mark.asyncio
async def test_pending_mode_writes_pending_approval_and_refreshes(
    sqlite_db, monkeypatch
):
    monkeypatch.setenv("AUTO_YETAI_PICKS_AUTO_PUBLISH", "false")
    await _run(sqlite_db, [_cand(1), _cand(2)])
    first = _bets(sqlite_db)
    assert [b.status for b in first] == ["pending_approval"] * 2
    ids = {b.id for b in first}

    await _run(sqlite_db, [_cand(1), _cand(2)], now=NOW + timedelta(hours=1))
    again = _bets(sqlite_db)
    assert {b.id for b in again} == ids and len(again) == 2
    assert all(b.status == "pending_approval" for b in again)
    assert all("grading" in b.prediction_factors for b in again)


@pytest.mark.asyncio
async def test_pending_mode_still_applies_hard_gates(sqlite_db, monkeypatch):
    monkeypatch.setenv("AUTO_YETAI_PICKS_AUTO_PUBLISH", "false")
    await _run(sqlite_db, [_cand(1, side=None)])
    assert _bets(sqlite_db) == []


@pytest.mark.asyncio
async def test_parlay_off_by_default(sqlite_db):
    await _run(sqlite_db, [_cand(i) for i in range(1, 5)])
    assert all(b.bet_type != BetType.PARLAY for b in _bets(sqlite_db))


@pytest.mark.asyncio
async def test_parlay_on_publishes_once_with_leg_grading(sqlite_db, monkeypatch):
    monkeypatch.setenv("AUTO_YETAI_PARLAY_ENABLED", "true")
    await _run(sqlite_db, [_cand(i) for i in range(1, 5)])
    parlays = [b for b in _bets(sqlite_db) if b.bet_type == BetType.PARLAY]
    assert len(parlays) == 1 and parlays[0].status == "active"
    assert all("grading" in leg for leg in parlays[0].parlay_legs)
    assert len([b for b in _bets(sqlite_db) if b.bet_type != BetType.PARLAY]) == 3

    await _run(sqlite_db, [_cand(i) for i in range(5, 9)], now=NOW + timedelta(hours=1))
    assert len([b for b in _bets(sqlite_db) if b.bet_type == BetType.PARLAY]) == 1


@pytest.mark.asyncio
async def test_dry_run_writes_nothing_and_returns_picks(sqlite_db):
    result = await _run(sqlite_db, [_cand(1), _cand(2)], dry_run=True)
    assert result.id is None and result.pick_count == 2
    assert [p.candidate.event_id for p in result.picks] == ["e1", "e2"]
    assert sqlite_db.query(YetAIBet).count() == 0
    assert sqlite_db.query(AutoPickRun).count() == 0


def test_dry_run_cli_function_prints_json_and_rolls_back(sqlite_db, capsys):
    from app.services.auto_pick.__main__ import dry_run

    out = dry_run(sqlite_db, SLATE, providers=[_provider([_cand(1)])])
    json.dumps(out, default=str)
    assert out["now_utc"] == "2026-05-22T15:00:00"  # 11:00 ET default
    (pick,) = out["would_publish"]
    assert pick["tier"] == "free" and pick["grading"]["market"] == "player_prop"
    assert sqlite_db.query(YetAIBet).count() == 0


@pytest.mark.asyncio
async def test_partial_when_one_provider_fails(sqlite_db):
    bad = AsyncMock()
    bad.get_candidates = AsyncMock(side_effect=RuntimeError("boom"))
    result = await AutoPickOrchestrator(
        db=sqlite_db, providers=[_provider([]), bad], now=NOW
    ).run()
    assert result.status == AutoPickRunStatus.PARTIAL


@pytest.mark.asyncio
async def test_failed_when_all_providers_fail(sqlite_db):
    bad = AsyncMock()
    bad.get_candidates = AsyncMock(side_effect=RuntimeError("boom"))
    result = await AutoPickOrchestrator(
        db=sqlite_db, providers=[bad, bad], now=NOW
    ).run()
    assert result.status == AutoPickRunStatus.FAILED and result.pick_count == 0


@pytest.mark.asyncio
async def test_no_providers_is_no_picks(sqlite_db):
    result = await AutoPickOrchestrator(db=sqlite_db, providers=[], now=NOW).run()
    assert result.status == AutoPickRunStatus.NO_PICKS


@pytest.mark.asyncio
async def test_result_id_matches_run_row(sqlite_db):
    result = await _run(sqlite_db, [_cand(1)])
    assert result.id == sqlite_db.query(AutoPickRun).one().id


@pytest.mark.asyncio
async def test_postgres_takes_advisory_lock_before_reading_todays_rows(
    sqlite_db, monkeypatch
):
    events = []
    real_execute = sqlite_db.execute

    def execute(stmt, *a, **kw):
        if "pg_advisory_xact_lock" in str(stmt):
            events.append(("lock", a[0]["k"]))
            return None
        return real_execute(stmt, *a, **kw)

    monkeypatch.setattr(orch_mod, "_dialect_name", lambda db: "postgresql")
    monkeypatch.setattr(sqlite_db, "execute", execute)
    real_load = AutoPickOrchestrator._load_today_auto_rows

    def load(self, dr):
        events.append(("read", None))
        return real_load(self, dr)

    monkeypatch.setattr(AutoPickOrchestrator, "_load_today_auto_rows", load)

    cands = [_cand(i) for i in range(1, 5)]
    await _run(sqlite_db, cands)
    assert events[:2] == [("lock", orch_mod.AUTO_PICK_LOCK_KEY), ("read", None)]
    assert len(_bets(sqlite_db)) == 3

    second = await _run(sqlite_db, cands, now=NOW + timedelta(minutes=1))
    assert second.pick_count == 0 and len(_bets(sqlite_db)) == 3


@pytest.mark.asyncio
async def test_no_lock_on_sqlite_or_dry_run(sqlite_db, monkeypatch):
    calls = []
    monkeypatch.setattr(orch_mod, "acquire_run_lock", lambda db: calls.append(db))
    await _run(sqlite_db, [_cand(1)], dry_run=True)
    assert calls == []
    await _run(sqlite_db, [_cand(1)])
    assert calls == [sqlite_db]  # sqlite: helper itself is a no-op


@pytest.mark.asyncio
async def test_market_concentration_counts_across_runs(sqlite_db):
    nba = [_cand(i, league="NBA") for i in (1, 2)]
    await _run(sqlite_db, nba)
    assert len(_bets(sqlite_db)) == 2

    later = await _run(
        sqlite_db,
        [_cand(3, league="NBA", commence=LATE), _cand(4, league="NHL", commence=LATE)],
        now=NOW + timedelta(hours=6),
    )
    assert later.pick_count == 1
    assert {b.sport for b in _bets(sqlite_db)} == {"NBA", "NHL"}
    assert _counts_last(sqlite_db) == {"market_concentration": 1}


@pytest.mark.asyncio
async def test_morning_reserves_a_slot_and_evening_fills_to_cap(sqlite_db):
    morning = await _run(
        sqlite_db, [_cand(i, commence=LATE) for i in range(1, 5)], reserve_slots=1
    )
    assert morning.pick_count == 2
    assert _counts_last(sqlite_db)["cap_reached"] == 2

    evening = await _run(
        sqlite_db,
        [_cand(i, commence=LATE) for i in range(5, 8)],
        now=NOW + timedelta(hours=6, minutes=30),
    )
    assert evening.pick_count == 1 and len(_bets(sqlite_db)) == 3


@pytest.mark.asyncio
async def test_early_only_slate_morning_does_not_reserve(sqlite_db):
    # Every game starts by 13:00 ET (before the 17:30 run + buffer): nothing for evening.
    early = NOW + timedelta(hours=2)
    res = await _run(
        sqlite_db, [_cand(i, commence=early) for i in range(1, 5)], reserve_slots=1
    )
    assert res.pick_count == 3


@pytest.mark.asyncio
async def test_early_only_slate_morning_fills_floor(sqlite_db):
    early = NOW + timedelta(hours=2)
    res = await _run(
        sqlite_db,
        [_cand(1, commence=early), _cand(2, 7.25, commence=early)],
        reserve_slots=1,
    )
    assert res.pick_count == 2  # floor fill is on when no reserve


@pytest.mark.asyncio
async def test_mixed_slate_morning_still_reserves(sqlite_db):
    early = NOW + timedelta(hours=2)
    cands = [_cand(i, commence=early) for i in (1, 2, 3)] + [_cand(4, commence=LATE)]
    res = await _run(sqlite_db, cands, reserve_slots=1)
    assert res.pick_count == 2


@pytest.mark.asyncio
async def test_morning_skips_floor_fill_and_evening_fills_to_two(sqlite_db):
    # 9.0 clears threshold; 7.25 / 7.1 clear only the floor.
    morning = await _run(
        sqlite_db,
        [
            _cand(1, commence=LATE),
            _cand(2, 7.25, commence=LATE),
            _cand(3, 7.1, commence=LATE),
        ],
        reserve_slots=1,
    )
    assert morning.pick_count == 1
    assert _counts_last(sqlite_db)["below_threshold"] == 2

    evening = await _run(
        sqlite_db,
        [_cand(2, 7.25, commence=LATE), _cand(3, 7.1, commence=LATE)],
        now=NOW + timedelta(hours=6, minutes=30),
    )
    assert evening.pick_count == 1 and len(_bets(sqlite_db)) == 2


@pytest.mark.asyncio
async def test_reserve_never_below_one_pick(sqlite_db):
    result = await _run(
        sqlite_db, [_cand(1, commence=LATE), _cand(2, commence=LATE)], reserve_slots=5
    )
    assert result.pick_count == 1


@pytest.mark.asyncio
async def test_bad_min_score_env_falls_back_with_warning(
    sqlite_db, monkeypatch, caplog
):
    monkeypatch.setenv("AUTO_YETAI_PICKS_MIN_SCORE", "fifty")
    assert orch_mod._min_score() == orch_mod.DEFAULT_MIN_SCORE
    assert "AUTO_YETAI_PICKS_MIN_SCORE" in caplog.text
    result = await _run(sqlite_db, [_cand(1)])
    assert result.pick_count == 1
