"""Shadow grader: measure every fair-price shadow flag against the close and the box score.

Reads odds_line_snapshots, box scores (pred_recent_games, the same rows the NBA accuracy services read) and writes only the grading
columns of fair_price_shadow_flags. Nothing published or auto-picked reads them. Every run
recomputes all grading fields of the flags in the window (idempotent; a missed night heals).

Actuals are wired for NBA only (RecentGames). Other sports get CLV, next-snapshot and baseline
fields but actual/result/units stay None.

The closing pool is the backtest's (backtest.close_scorer), so a flag's close_prob / clv equal
the backtest's p_close / clv for the same flag.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.models.predictions_models import FairPriceShadowFlag as F
from app.models.predictions_models import OddsLineSnapshot as S
from app.services import accuracy_shared, odds_math
from app.services.fair_price import backtest, flags as fp, shadow
from app.services.fair_price import weights as weights_mod

log = logging.getLogger(__name__)

CLOSE_MAX_LEAD_MIN = 60
LOOKBACK_DAYS = 7
NBA = "basketball_nba"
GRADE_AFTER = timedelta(hours=4)


def _eastern_today() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def _baseline(qs, flag, rule, p_close, stat, close_ok) -> dict | None:
    """The random pick of backtest.replay_group (same seed, candidates and scoring)."""
    t = flag.observed_at
    cands = sorted(
        (q.book, q.line, s_, q.over_price if s_ == "o" else q.under_price)
        for q in backtest._present(qs, t)
        if q.book not in rule.reference_only
        and q.book not in rule.consensus_only
        and fp._fresh(q, t, rule)
        for s_ in ("o", "u")
        if (q.over_price if s_ == "o" else q.under_price)
    )
    if not cands:
        return None
    b, ln, sd, pr = backtest._rng(
        0, "rand", flag.event_id, flag.market, flag.player_key, flag.book, flag.side
    ).choice(cands)
    pc, _ = p_close(ln, sd)
    clv = pc - odds_math.american_to_prob(pr) if close_ok and pc is not None else None
    return {
        "book": b,
        "side": sd,
        "line": ln,
        "price": pr,
        "clv": clv,
        "win": backtest._win(stat, ln, sd),
    }


def _grade_flag(f, qs, times, close, rule, weights, actuals, now, stats) -> None:
    commence = f.commence_time
    f.is_close = close is not None and f.observed_at == close
    f.close_at = close
    close_probs = (
        fp.book_fair(backtest._present(qs, close), close, rule) if close else {}
    )
    p_close = backtest.close_scorer(close_probs, weights, f.market)
    pc, nc = p_close(f.line, f.side)
    if close is None or not close_probs:
        note = "no_close"
    elif (commence - close).total_seconds() > CLOSE_MAX_LEAD_MIN * 60:
        note = "stale_close"
    elif pc is None:
        note = "no_conversion"
    else:
        note = "ok"
    ok = note == "ok"
    f.close_note = note
    f.close_prob = pc if ok else None
    f.n_close = nc if ok else None
    f.clv = pc - odds_math.american_to_prob(f.price) if ok and not f.is_close else None

    # actuals (NBA only)
    f.actual = f.result = f.units = None
    if f.sport == NBA and f.game_date is not None:
        key_to_id, box, box_days = actuals
        stat, void = backtest._stat(f.market, f.player_key, f.game_date, key_to_id, box)
        has_box_day = f.game_date in box_days
        if void == "no_player":
            f.result = "ungraded"
        elif stat is None and not has_box_day:
            f.result = None  # pending: box scores not in yet
        else:
            f.result = accuracy_shared.ou_row_result(
                line=f.line, pick=f.side, actual=stat, actual_expected=has_box_day
            )
        f.actual = stat
        if f.result in ("hit", "miss", "push"):
            f.units = odds_math.units_for_result(f.result, f.price)
    else:
        stat = None

    # how long the flag lives: the flagged book's next snapshot
    f.next_at = f.next_price = f.next_playable = None
    later = [t for t in times if t > f.observed_at]
    if later:
        tn = later[0]
        f.next_at = tn
        for q in backtest._present(qs, tn):
            if q.book == f.book and q.line == f.line:
                price = q.over_price if f.side == "o" else q.under_price
                if price:
                    f.next_price = int(price)
                    break
        f.next_playable = f.next_price is not None and odds_math.american_to_decimal(
            f.next_price
        ) >= odds_math.american_to_decimal(f.playable_to)

    f.baseline = _baseline(qs, f, rule, p_close, stat, ok)
    f.graded_at = now

    stats["flags"] += 1
    stats["by_close_note"][note] = stats["by_close_note"].get(note, 0) + 1
    stats["is_close"] += bool(f.is_close)
    if f.result in ("hit", "miss", "push"):
        stats["graded"] += 1
    elif f.result in ("ungraded", "dnp"):
        stats["void"] += 1
    else:
        stats["pending"] += 1


def run(
    today: date | None = None,
    db=None,
    now: datetime | None = None,
    lookback_days: int = LOOKBACK_DAYS,
    rule: fp.FlagRule | None = None,
) -> dict:
    """Grade the window [today - lookback_days, today - 1]; never raises. ``rule`` is the
    rule the flags were made with (default: the live default_rule(); it decides the random
    baseline's candidate books)."""
    if not shadow.enabled():
        return {"status": "disabled"}
    own = db is None
    try:
        if own:
            from app.core.database import SessionLocal

            db = SessionLocal()
        return _run(
            db,
            today or _eastern_today(),
            now or shadow._naive_now(),
            lookback_days,
            rule or fp.default_rule(),
        )
    except Exception as e:  # noqa: BLE001 - a shadow job must never take a worker down
        log.exception("fair_price shadow grader failed")
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}
    finally:
        if own and db is not None:
            db.close()


def _run(db, today, now, lookback_days, rule) -> dict:
    lo, hi = today - timedelta(days=lookback_days), today - timedelta(days=1)
    groups = (
        db.query(F.event_id, F.market)
        .filter(
            F.game_date >= lo,
            F.game_date <= hi,
            F.commence_time < now - GRADE_AFTER,
        )
        .distinct()
        .all()
    )
    stats = {
        "flags": 0,
        "graded": 0,
        "void": 0,
        "pending": 0,
        "by_close_note": {},
        "is_close": 0,
    }
    out = {"status": "ok", "groups": len(groups)}
    if not groups:
        out.update(stats)
        return out
    key_to_id, _ = backtest.load_player_keys(db)
    box = backtest.load_box(db, lo, hi)
    actuals = (key_to_id, box, {d for _, d in box})
    wcache: dict = {}
    for event_id, market in sorted(groups):
        try:
            rows = db.query(S).filter(S.event_id == event_id, S.market == market).all()
            players = backtest._group([shadow._snap(r) for r in rows]).get(
                (event_id, market), {}
            )
            times = backtest._times(players) if players else []
            close = times[-1] if times else None
            flag_rows = (
                db.query(F)
                .filter(
                    F.event_id == event_id,
                    F.market == market,
                    F.game_date >= lo,
                    F.game_date <= hi,
                    F.commence_time < now - GRADE_AFTER,
                )
                .all()
            )
            for f in flag_rows:
                k = (f.weights_version, f.sport, f.market)
                if k not in wcache:
                    wcache[k] = weights_mod.by_version(db, *k)
                _grade_flag(
                    f,
                    players.get(f.player_key, []),
                    times,
                    close,
                    rule,
                    wcache[k],
                    actuals,
                    now,
                    stats,
                )
            db.commit()
        except Exception:  # noqa: BLE001 - one bad group must not stop the rest
            db.rollback()
            log.exception("fair_price grade: group %s/%s failed", event_id, market)
            stats["errors"] = stats.get("errors", 0) + 1
    out.update(stats)
    return out
