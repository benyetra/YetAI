"""verify_pending_yetai_bets: every shown bet reaches a terminal state, row by row."""

import logging
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.models.database_models import BetSource, BetType, SubscriptionTier, YetAIBet
from app.services import yetai_grading as yg
from app.services.yetai_bets_service_db import (
    YetAIBetsServiceDB,
    set_yetai_auto_grade_hold,
    yetai_auto_grade_held,
)
from tests.test_espn_results import _load, espn  # noqa: F401

NOW = datetime.utcnow()
_ids = iter(range(10_000))


def tried_since(days):
    """prediction_factors of a bet whose first settlement attempt was `days` ago."""
    first = (NOW - timedelta(days=days)).isoformat()
    return {"settlement": {"attempts": 1, "first_attempt_at": first}}


def mk(**kw):
    """Unsaved YetAIBet that is past its game window (gradeable) by default."""
    kw.setdefault("id", f"bet-{next(_ids)}")
    kw.setdefault("bet_type", BetType.MONEYLINE)
    kw.setdefault("selection", "Toronto Raptors ML")
    kw.setdefault("sport", "NBA")
    kw.setdefault("status", "active")
    kw.setdefault("home_team", "Toronto Raptors")
    kw.setdefault("away_team", "Philadelphia 76ers")
    kw.setdefault("commence_time", NOW - timedelta(days=1))
    kw.setdefault("created_at", NOW - timedelta(days=2))
    kw.setdefault("prediction_factors", {})
    return YetAIBet(
        title="t",
        description="",
        odds=-110,
        confidence=80,
        tier_requirement=SubscriptionTier.FREE,
        **kw,
    )


class FakeDB:
    """query().filter().order_by().limit().all(): main batch first, legacy batch second."""

    def __init__(self, main=(), legacy=()):
        self.batches = [list(main), list(legacy)]
        self.filters, self.limits, self.orders = [], [], []
        self.calls = self.commits = self.rollbacks = 0
        self.first_row = None

    def query(self, *_):
        return self

    def filter(self, *exprs):
        self.filters.append(
            [str(e.compile(compile_kwargs={"literal_binds": True})) for e in exprs]
        )
        return self

    def order_by(self, *cols):
        self.orders.append([str(c) for c in cols])
        return self

    def limit(self, n):
        self.limits.append(n)
        return self

    def all(self):
        rows = self.batches[self.calls] if self.calls < 2 else []
        self.calls += 1
        return rows

    def with_for_update(self, **kw):
        self.locked = kw
        return self

    def populate_existing(self):
        return self

    def first(self):
        if self.first_row is not None:
            return self.first_row
        last = " ".join(self.filters[-1]) if self.filters else ""
        rows = [b for batch in self.batches for b in batch]
        return next((b for b in rows if f"'{b.id}'" in last), None)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def run(db, *outcomes, side_effect=None):
    """Run the settlement loop on `db` with grade_pick returning/raising `outcomes` in order."""
    service = YetAIBetsServiceDB()
    with (
        patch("app.services.yetai_bets_service_db.SessionLocal", return_value=db),
        patch.object(service, "_expire_stale_pending_approval", return_value=0),
        patch(
            "app.services.yetai_grading.grade_pick",
            side_effect=side_effect or list(outcomes),
        ) as grade,
    ):
        result = service.verify_pending_yetai_bets()
    return result, grade


def O(kind, text=""):
    return yg.Outcome(kind, text)


# --- straight bets ---------------------------------------------------------


@pytest.mark.parametrize("kind", ["won", "lost", "pushed", "void"])
def test_terminal_outcome_is_written(kind):
    bet = mk()
    result, _ = run(FakeDB([bet]), O(kind, "why"))
    assert bet.status == kind and bet.result == "why" and bet.settled_at
    assert result["success"] and result["expired"] == 0
    assert result["settled"] == 1 and result["voided"] == (kind == "void")
    s = bet.prediction_factors["settlement"]
    assert s["attempts"] == 1 and s["last_attempt_at"]
    assert s["last_error"] == ("why" if kind == "void" else None)


def test_not_ready_inside_window_stays_active_and_counts_attempts():
    bet = mk()
    run(FakeDB([bet]), O("not_ready", "Game not found"))
    run(FakeDB([bet]), O("not_ready", "Game not found"))
    assert bet.status == "active"
    assert bet.prediction_factors["settlement"]["attempts"] == 2
    assert bet.prediction_factors["settlement"]["last_error"] == "Game not found"


def test_past_retry_window_ends_void_never_expired(caplog, monkeypatch):
    monkeypatch.delenv("YETAI_SETTLE_RETRY_DAYS", raising=False)
    old = mk(
        commence_time=NOW - timedelta(days=5),
        created_at=NOW - timedelta(days=6),
        prediction_factors=tried_since(5),
    )
    fresh = mk(commence_time=NOW - timedelta(days=2))
    with caplog.at_level(logging.ERROR):
        result, _ = run(
            FakeDB([old, fresh]), O("not_ready", "Game not found"), O("not_ready", "x")
        )
    assert old.status == "void" and old.result == "Ungradeable: Game not found"
    assert fresh.status == "active"
    assert "YETAI_SETTLEMENT_VOID" in caplog.text and old.id in caplog.text
    assert result["voided"] == 1 and result["expired"] == 0


def test_retry_window_env_override(monkeypatch):
    monkeypatch.setenv("YETAI_SETTLE_RETRY_DAYS", "10")
    bet = mk(commence_time=NOW - timedelta(days=5))
    run(FakeDB([bet]), O("not_ready", "Game not found"))
    assert bet.status == "active"


def test_ungradeable_voids_immediately_and_logs(caplog):
    bet = mk()
    with caplog.at_level(logging.ERROR):
        run(FakeDB([bet]), O("ungradeable", "Unsupported: NBA total_bases"))
    assert bet.status == "void"
    assert bet.result == "Ungradeable: Unsupported: NBA total_bases"
    assert "YETAI_SETTLEMENT_VOID" in caplog.text


def test_not_gradeable_yet_makes_no_api_call():
    bet = mk(commence_time=NOW + timedelta(hours=1))
    _, grade = run(FakeDB([bet]), O("won"))
    assert bet.status == "active" and grade.call_count == 0


def test_bad_row_does_not_block_or_roll_back_the_next():
    bad, good = mk(), mk()
    db = FakeDB([bad, good])
    result, _ = run(db, side_effect=[RuntimeError("boom"), O("won", "ok")])
    assert bad.status == "active" and good.status == "won"
    assert db.rollbacks == 1 and db.commits >= 2
    assert "boom" in bad.prediction_factors["settlement"]["last_error"]
    assert result["success"] and result["settled"] == 1


# --- candidates ------------------------------------------------------------


def test_candidate_queries_cover_legacy_but_never_rejected():
    db = FakeDB()
    run(db)
    text = " ".join(" ".join(f) for f in db.filters)
    for status in ("active", "pending", "expired", "pending_manual_review"):
        assert status in text
    assert "rejected" not in text and "pending_approval" not in text
    assert "Admin expired%" in text and "Auto-expired%" in text
    assert "settled_at IS NOT NULL" in text and "Evaluation%" in text
    assert db.limits == [50] and "created_at" in db.orders[0][0]


def test_rejected_row_is_never_modified():
    rejected = mk(status="rejected", result="Auto-expired (unapproved)")
    result, grade = run(FakeDB([rejected]), O("won"))
    assert rejected.status == "rejected" and grade.call_count == 0
    assert result["settled"] == 0


def test_legacy_expired_row_is_regraded():
    row = mk(status="expired", result="Unsettled >24h, no result", settled_at=NOW)
    run(FakeDB([], [row]), O("won", "Won: Raptors"))
    assert row.status == "won"


def test_legacy_not_ready_in_window_is_left_as_is_then_voided_after():
    inside = mk(status="pending_manual_review", commence_time=NOW - timedelta(days=1))
    outside = mk(
        status="expired",
        result="Unsettled >24h, no result",
        settled_at=NOW - timedelta(days=9),
        commence_time=NOW - timedelta(days=9),
        prediction_factors=tried_since(9),
    )
    run(FakeDB([], [inside, outside]), O("not_ready", "n"), O("not_ready", "n"))
    assert inside.status == "pending_manual_review"
    assert outside.status == "void" and outside.result == "Ungradeable: n"


def test_legacy_never_approved_row_is_skipped():
    row = mk(status="expired", result="Auto-expired (unapproved)")
    _, grade = run(FakeDB([], [row]), O("won"))
    assert row.status == "expired" and grade.call_count == 0


def test_error_loss_retry_only_applies_a_real_outcome():
    kw = dict(status="lost", result="Evaluation error: x", bet_type=BetType.PROP)
    a, b = mk(sport="MLB", **kw), mk(sport="MLB", **kw)
    run(FakeDB([a, b]), O("won", "w"), O("ungradeable", "u"))
    assert a.status == "won" and b.status == "lost"


# --- hold ------------------------------------------------------------------


def _held(age):
    bet = mk()
    set_yetai_auto_grade_hold(bet)
    if age is None:
        bet.prediction_factors = {"auto_grade_hold": True}
    else:
        bet.prediction_factors["auto_grade_hold_at"] = (NOW - age).isoformat()
    return bet


def test_hold_blocks_for_24h_only():
    assert yetai_auto_grade_held(_held(timedelta(hours=1)), NOW) is True
    assert yetai_auto_grade_held(_held(timedelta(hours=25)), NOW) is False
    assert yetai_auto_grade_held(_held(None), NOW) is False
    bet = _held(timedelta(hours=1))
    set_yetai_auto_grade_hold(bet, held=False)
    assert bet.prediction_factors == {}


def test_hold_skips_grading_until_elapsed():
    held, elapsed = _held(timedelta(hours=1)), _held(timedelta(hours=25))
    _, grade = run(FakeDB([held, elapsed]), O("won"))
    assert held.status == "active" and elapsed.status == "won"
    assert grade.call_count == 1


def test_reopen_clears_leg_status_and_result():
    from app.api.admin_yetai_picks import _clear_parlay_leg_results

    legs = [{"pick": "a", "leg_status": "won", "leg_result": "x", "odds": "-110"}]
    assert _clear_parlay_leg_results(legs) == [{"pick": "a", "odds": "-110"}]


# --- parlays through the loop ---------------------------------------------


def parlay(*legs, **kw):
    legs = [
        {
            "sport": "NBA",
            "bet_type": "Moneyline",
            "pick": f"Team {i}",
            "home_team": "H",
            "away_team": "A",
            "game": "A @ H",
            "odds": "-110",
            **leg,
        }
        for i, leg in enumerate(legs)
    ]
    return mk(bet_type=BetType.PARLAY, selection="Parlay", parlay_legs=legs, **kw)


def test_parlay_lost_leg_settles_while_other_leg_pending():
    bet = parlay({}, {})
    run(FakeDB([bet]), O("lost", "L"), O("not_ready", "Game not found"))
    assert bet.status == "lost"
    assert [leg["leg_status"] for leg in bet.parlay_legs] == ["lost", "pending"]


def test_parlay_with_void_leg_settles_on_the_rest():
    bet = parlay({}, {}, {})
    run(FakeDB([bet]), O("won", "w"), O("void", "Postponed"), O("won", "w"))
    assert bet.status == "won"
    assert [leg["leg_status"] for leg in bet.parlay_legs] == ["won", "void", "won"]


def test_parlay_all_void_is_void_and_ungradeable_leg_is_void():
    bet = parlay({}, {})
    run(FakeDB([bet]), O("void", "Postponed"), O("ungradeable", "Could not parse pick"))
    assert bet.status == "void"
    assert bet.parlay_legs[1]["leg_result"] == "Ungradeable: Could not parse pick"


def test_parlay_waits_and_persists_pending_leg_status():
    bet = parlay({}, {})
    run(FakeDB([bet]), O("won", "w"), O("not_ready", "Game not found"))
    assert bet.status == "active"
    assert [leg["leg_status"] for leg in bet.parlay_legs] == ["won", "pending"]
    assert bet.parlay_legs[1]["leg_result"] == "Game not found"


def test_parlay_does_not_regrade_terminal_legs():
    bet = parlay({"leg_status": "won", "leg_result": "w"}, {})
    _, grade = run(FakeDB([bet]), O("won", "w"))
    assert grade.call_count == 1 and bet.status == "won"


def test_parlay_past_window_voids_pending_legs_and_settles_on_rest():
    bet = parlay(
        {"commence_time": (NOW - timedelta(days=9)).isoformat()},
        {"commence_time": (NOW - timedelta(days=9)).isoformat()},
        commence_time=None,
        prediction_factors=tried_since(9),
    )
    run(FakeDB([bet]), O("won", "w"), O("not_ready", "Game not found"))
    assert bet.status == "won"
    assert bet.parlay_legs[1]["leg_status"] == "void"


# --- real grading through ESPN fixtures ------------------------------------


def _meta(market, side, line, **extra):
    return {
        "market": market,
        "league": "NBA",
        "game_date": "2026-01-11",
        "home_team": "Toronto Raptors",
        "away_team": "Philadelphia 76ers",
        "side": side,
        "line": line,
        **extra,
    }


def _real(bet, expected, **checks):
    service = YetAIBetsServiceDB()
    db = FakeDB([bet])
    with (
        patch("app.services.yetai_bets_service_db.SessionLocal", return_value=db),
        patch.object(service, "_expire_stale_pending_approval", return_value=0),
    ):
        service.verify_pending_yetai_bets()
    assert bet.status == expected, bet.result
    for key, value in checks.items():
        assert getattr(bet, key) == value


def _nba(market, bet_type, **kw):
    grading = kw.pop("grading", None)
    return mk(
        bet_type=bet_type,
        prediction_factors={"grading": grading} if grading else {},
        commence_time=datetime(2026, 1, 11, 23, 0),
        **kw,
    )


def test_postponed_game_is_void(espn):
    espn.boards[("mlb", "20250425")] = _load("mlb_postponed_scoreboard_20250425.json")
    grading = {
        "market": "total",
        "league": "MLB",
        "game_date": "2025-04-25",
        "home_team": "Detroit Tigers",
        "away_team": "Baltimore Orioles",
        "side": "over",
        "line": 8.5,
    }
    bet = mk(
        bet_type=BetType.TOTAL,
        sport="MLB",
        commence_time=datetime(2025, 4, 25, 23, 0),
        prediction_factors={"grading": grading},
    )
    _real(bet, "void", result="Postponed")


def test_player_did_not_play_is_void(espn):
    grading = _meta("player_prop", "over", 5.5, player="Paul George", stat="points")
    bet = _nba("prop", BetType.PROP, grading=grading, selection="x")
    _real(bet, "void", result="DNP: Paul George")


def test_whole_number_line_pushes(espn):
    bet = _nba("spread", BetType.SPREAD, grading=_meta("spread", "home", -1.0))
    _real(bet, "pushed")


def test_admin_pick_without_grading_settles_from_selection_text(espn):
    bet = _nba("spread", BetType.SPREAD, selection="Philadelphia 76ers +1.5")
    _real(bet, "won")
    lost = _nba("spread", BetType.SPREAD, selection="Toronto Raptors -3.5")
    _real(lost, "lost")


def test_unsupported_sport_ends_void_with_reason(espn):
    bet = mk(sport="Tennis", selection="Sinner ML", home_team="Sinner", away_team="X")
    _real(bet, "void")
    assert bet.result.startswith("Ungradeable")


# --- review fixes: legacy sweep against a real SQL engine ------------------


@pytest.fixture
def sqlite_db():
    from sqlalchemy import create_engine
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.orm import sessionmaker

    @compiles(JSONB, "sqlite")
    def _jsonb(type_, compiler, **kw):  # noqa: ARG001
        return "JSON"

    engine = create_engine("sqlite://")
    from app.models.simple_unified_bet_model import SimpleUnifiedBet

    YetAIBet.__table__.create(engine)
    SimpleUnifiedBet.__table__.create(
        engine
    )  # auto admin-expired rows look up user copies
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


# (id, status, result, settled_at set?) -> swept by the legacy query?
LEGACY_SHAPES = [
    # old grader (469d9201/82db5be8) parked stale shown picks
    ("pmr", "pending_manual_review", "Auto-expired: game started >24h ago", True, True),
    # old grader (aa655ff2..) expired stale shown picks with settled_at
    ("grader", "expired", "Unsettled >24h, no result", True, True),
    ("grader-kept", "expired", "Evaluation error: x", True, True),
    # unapproved queue expiry (expire_pending_picks before 7f12466c): no result/settled_at
    ("queue", "expired", None, False, False),
    ("queue-settled-null", "expired", None, True, False),
    # admin expire endpoint, any status
    # (manual -> "admin" is moved to void, see below; an auto one without a linked user
    # copy cannot be told from a never-approved queue row, so it stays)
    ("admin", "expired", "Admin expired (stale pick)", True, False),
    ("admin-auto", "expired", "Admin expired (stale pick)", True, False),
    ("unapproved", "expired", "Auto-expired (unapproved)", True, False),
    ("rejected", "rejected", "Auto-expired (unapproved)", True, False),
    ("approval", "pending_approval", None, False, False),
]


def _add_shapes(db):
    for bet_id, status, result, settled, _ in LEGACY_SHAPES:
        db.add(
            mk(
                id=bet_id,
                status=status,
                result=result,
                settled_at=NOW - timedelta(days=30) if settled else None,
                source=BetSource.AUTO if bet_id.endswith("-auto") else BetSource.MANUAL,
            )
        )
    db.commit()


def test_legacy_query_against_sql_matches_history(sqlite_db):
    _add_shapes(sqlite_db)
    service = YetAIBetsServiceDB()
    got = {b.id for b in service._settle_candidates(sqlite_db)}
    # graded again, plus the manual admin-expired row that is moved to void
    assert got == {s[0] for s in LEGACY_SHAPES if s[4]} | {"admin"}
    for bet in sqlite_db.query(YetAIBet).all():
        want = next(s[4] for s in LEGACY_SHAPES if s[0] == bet.id)
        assert service._legacy_sweepable(bet) is want, bet.id


def test_full_loop_on_sql_session_grades_only_shown_legacy_rows(sqlite_db):
    _add_shapes(sqlite_db)
    service = YetAIBetsServiceDB()
    with (
        patch(
            "app.services.yetai_bets_service_db.SessionLocal", return_value=sqlite_db
        ),
        patch.object(sqlite_db, "close"),
        patch("app.services.yetai_grading.grade_pick", return_value=O("won", "w")),
    ):
        result = service.verify_pending_yetai_bets()
    status = {b.id: b.status for b in sqlite_db.query(YetAIBet).all()}
    assert {k for k, v in status.items() if v == "won"} == {
        "pmr",
        "grader",
        "grader-kept",
    }
    assert status["queue"] == "expired" and status["admin-auto"] == "expired"
    assert status["admin"] == "void"  # shown manual pick pulled by an admin: in history
    admin = sqlite_db.query(YetAIBet).get("admin")
    assert admin.result == "Admin expired (stale pick)" and admin.settled_at
    # never-shown rows are not resurrected
    assert status["rejected"] == "rejected" and status["unapproved"] == "expired"
    assert status["approval"] == "rejected"  # stale queue pick: rejected, never graded
    assert result["settled"] == 4 and result["voided"] == 1


# --- review fixes: error vs not_ready vs backstop ---------------------------


def test_error_inside_backstop_never_voids_even_past_window():
    bet = mk(commence_time=NOW - timedelta(days=9), prediction_factors=tried_since(9))
    run(FakeDB([bet]), O("error", "ESPN error: 503"))
    assert bet.status == "active"
    s = bet.prediction_factors["settlement"]
    assert s["last_kind"] == "error" and s["last_error"] == "ESPN error: 503"


def test_waiting_game_past_window_is_not_voided():
    bet = mk(commence_time=NOW - timedelta(days=9), prediction_factors=tried_since(9))
    run(FakeDB([bet]), O("not_ready", "in_progress"))
    assert bet.status == "active"


def test_errors_only_past_backstop_void_and_log(caplog):
    bet = mk(commence_time=NOW - timedelta(days=20), prediction_factors=tried_since(20))
    with caplog.at_level(logging.ERROR):
        run(FakeDB([bet]), O("error", "ESPN error: timeout"))
    assert bet.status == "void" and bet.result == "Ungradeable: ESPN error: timeout"
    assert "YETAI_SETTLEMENT_VOID" in caplog.text


def test_first_attempt_is_recorded_and_anchors_the_window():
    # an old row seen for the first time gets a full window, then voids after it
    bet = mk(commence_time=NOW - timedelta(days=60))
    run(FakeDB([bet]), O("not_ready", "Game not found"))
    assert bet.status == "active"
    first = bet.prediction_factors["settlement"]["first_attempt_at"]
    run(FakeDB([bet]), O("not_ready", "Game not found"))
    assert bet.prediction_factors["settlement"]["first_attempt_at"] == first
    bet.prediction_factors = tried_since(4)
    run(FakeDB([bet]), O("not_ready", "Game not found"))
    assert bet.status == "void"


# --- review fixes: parlays --------------------------------------------------


def test_reduced_parlay_stores_effective_odds_and_units_use_it():
    bet = parlay({"odds": "+100"}, {"odds": "+100"}, {"odds": "-110"})
    run(FakeDB([bet]), O("won", "w"), O("void", "Postponed"), O("won", "w"))
    assert bet.status == "won" and bet.odds == -110  # posted price unchanged
    eff = bet.prediction_factors["settlement"]["effective_odds"]
    assert eff == 281.82  # 2.0 * 1.909 = 3.818 decimal
    stats = YetAIBetsServiceDB().compute_history_stats(
        [{"status": "won", "odds": bet.odds, "effective_odds": eff}], 30
    )
    assert stats["units"] == 2.82


def test_all_pushed_parlay_is_void():
    bet = parlay({}, {})
    run(FakeDB([bet]), O("pushed", "p"), O("pushed", "p"))
    assert bet.status == "void"


@pytest.mark.parametrize("legs", [None, [], "not json", "[]", '"x"'])
def test_parlay_without_usable_legs_is_void(legs):
    bet = mk(bet_type=BetType.PARLAY, selection="Parlay", parlay_legs=legs)
    _, grade = run(FakeDB([bet]))
    assert bet.status == "void" and "no usable legs" in bet.result
    assert grade.call_count == 0


def test_parlay_legs_json_string_is_parsed_and_graded():
    import json

    legs = [{"sport": "NBA", "bet_type": "Moneyline", "pick": "a", "odds": "-110"}] * 2
    bet = mk(bet_type=BetType.PARLAY, selection="Parlay", parlay_legs=json.dumps(legs))
    run(FakeDB([bet]), O("won", "w"), O("won", "w"))
    assert bet.status == "won" and isinstance(bet.parlay_legs, list)


def test_parlay_leg_error_keeps_waiting_past_window():
    old = {"commence_time": (NOW - timedelta(days=9)).isoformat()}
    bet = parlay(old, old, commence_time=None, prediction_factors=tried_since(9))
    run(FakeDB([bet]), O("won", "w"), O("error", "ESPN error: 500"))
    assert bet.status == "active"
    assert bet.parlay_legs[1]["leg_status"] == "pending"
    assert bet.prediction_factors["settlement"]["last_kind"] == "error"


# --- review fixes: concurrent settlers --------------------------------------


class PgFakeDB(FakeDB):
    def get_bind(self):
        from types import SimpleNamespace

        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))


def test_postgres_loads_each_bet_with_skip_locked():
    bet = mk()
    db = PgFakeDB([bet])
    db.locked = None
    run(db, O("won", "w"))
    assert db.locked == {"skip_locked": True} and bet.status == "won"


def test_row_locked_elsewhere_or_already_settled_is_skipped():
    locked, raced = mk(), mk()
    db = FakeDB([locked, raced])
    loads = iter([None, mk(id=raced.id, status="lost", result="Lost: x")])
    db.first = lambda: next(loads)  # None = skip_locked; then a row another run settled
    result, grade = run(db, O("won", "w"))
    assert grade.call_count == 0 and result["settled"] == 0
    assert locked.status == "active"
