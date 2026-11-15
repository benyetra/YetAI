"""Shadow flagger: record every fair-price flag the live snapshots produce, grade nothing.

Reads odds_line_snapshots only (never calls the Odds API) and writes fair_price_shadow_flags.
Nothing published or auto-picked reads either. It evaluates each observation time of an
(event, market) in (now - max_age, now] through the backtest's own code path
(backtest._present / fast_prop_flags), so a live run is the backtest replayed at the fetch times.
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
import os
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.models.predictions_models import FairPriceShadowFlag as F
from app.models.predictions_models import OddsLineSnapshot as S
from app.services import odds_math
from app.services.fair_price import backtest, weights as weights_mod
from app.services.fair_price import flags as fp

log = logging.getLogger(__name__)

RULE_VERSION = "fp-shadow-v1"
ENGINE_VERSION = "fair_price-2026.11.15"
PRIMARY = {("basketball_nba", "player_rebounds"), ("basketball_nba", "player_assists")}
RECENT_HOURS = 36


def enabled() -> bool:
    return os.environ.get("FAIR_PRICE_SHADOW_ENABLED", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def rule_version(rule: fp.FlagRule) -> str:
    """RULE_VERSION for the shipped rule, else RULE_VERSION+hash of its fields."""
    shipped = fp.FlagRule(
        consensus_only=frozenset(odds_math.CONSENSUS_ONLY_DEFAULT.split(","))
    )
    if rule == shipped:
        return RULE_VERSION
    parts = []
    for f in dataclasses.fields(rule):
        v = getattr(rule, f.name)
        parts.append((f.name, sorted(v) if isinstance(v, frozenset) else v))
    return f"{RULE_VERSION}+{hashlib.sha1(repr(parts).encode()).hexdigest()[:8]}"


def _naive_now() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


def _snap(r) -> backtest.SnapQuote:
    return backtest.SnapQuote(
        r.event_id,
        r.market,
        r.player_key,
        r.book,
        r.line,
        r.over_price,
        r.under_price,
        r.first_seen_at,
        r.last_seen_at,
        r.commence_time,
        r.game_date,
    )


def _consensus(present, t, market, weights, rule, flag) -> dict:
    """{book: {line, p, w}} of the leave-one-out pool behind the flag."""
    probs = fp.book_fair(present, t, rule)
    got, _, _ = backtest._pools(probs, weights, market)(flag.line)
    w = weights or {}
    out = {}
    for b, p in got.items():
        if b == flag.book:
            continue
        ln, _p = min(probs[b], key=lambda x: (abs(x[0] - flag.line), abs(x[1] - 0.5)))
        out[b] = {"line": ln, "p": p, "w": w.get(b, 1.0)}
    return out


def _group_flags(db, key, rows, now, window_start, rule, rv, wcache, override, stats):
    sport, event_id, market = key
    players = backtest._group([_snap(r) for r in rows]).get((event_id, market))
    if not players:
        return
    commence = next(iter(players.values()))[0].commence_time
    if (sport, market) in wcache:
        weights, wver = wcache[(sport, market)]
    else:
        if override is not None:
            weights = override.get((sport, market))
            wver = "override" if (sport, market) in override else weights_mod.EQUAL
        else:
            weights, wver = weights_mod.active(db, sport, market)
        wcache[(sport, market)] = (weights, wver)
    existing = {
        (e.player_key, e.side, e.book): e
        for e in db.query(F).filter(
            F.rule_version == rv, F.event_id == event_id, F.market == market
        )
    }
    times = [t for t in backtest._times(players) if window_start <= t <= now]
    stats["times"] += len(times)
    tier = "primary" if (sport, market) in PRIMARY else "secondary"
    for t in times:
        if t >= commence:
            continue
        for pk, qs in players.items():
            present = backtest._present(qs, t)
            for f in backtest.fast_prop_flags(
                present, t, market, weights, rule, commence
            ):
                k = (pk, f.side, f.book)
                row = existing.get(k)
                if row is not None:
                    if t > row.last_qualified_at:
                        row.last_qualified_at = t
                        row.last_line, row.last_price = f.line, f.price
                        row.n_qualified += 1
                        stats["updated"] += 1
                    continue
                q = next(
                    (x for x in present if x.book == f.book and x.line == f.line), None
                )
                src = next(
                    (
                        r
                        for r in rows
                        if r.player_key == pk
                        and r.book == f.book
                        and r.line == f.line
                        and r.first_seen_at <= t <= r.last_seen_at
                    ),
                    None,
                )
                row = F(
                    rule_version=rv,
                    engine_version=ENGINE_VERSION,
                    tier=tier,
                    sport=sport,
                    event_id=event_id,
                    game_date=q.game_date if q else None,
                    commence_time=commence,
                    market=market,
                    player_key=pk,
                    player_name=src.player_name if src else None,
                    side=f.side,
                    book=f.book,
                    line=f.line,
                    price=f.price,
                    book_updated_at=src.book_updated_at if src else None,
                    observed_at=t,
                    flagged_at=now,
                    quote_age_min=(now - t).total_seconds() / 60,
                    hours_before=(commence - t).total_seconds() / 3600,
                    fair_prob=f.fair_prob,
                    ev=f.ev,
                    playable_to=f.playable_to,
                    n_books=f.n_books,
                    devig_method=rule.method,
                    weights_version=wver,
                    consensus=_consensus(present, t, market, weights, rule, f),
                    last_qualified_at=t,
                    last_line=f.line,
                    last_price=f.price,
                    n_qualified=1,
                )
                db.add(row)
                existing[k] = row
                stats["new"] += 1
                stats["by_tier"][tier] = stats["by_tier"].get(tier, 0) + 1


def run(now=None, db=None, rule=None, weights_override=None) -> dict:
    """Flag the current window; never raises."""
    if not enabled():
        return {"status": "disabled"}
    own = db is None
    try:
        if own:
            from app.core.database import SessionLocal

            db = SessionLocal()
        return _run(
            db, now or _naive_now(), rule or fp.default_rule(), weights_override
        )
    except Exception as e:  # noqa: BLE001 - a shadow job must never take a worker down
        log.exception("fair_price shadow flagger failed")
        try:
            db.rollback()  # a caller's session must not be left in an aborted transaction
        except Exception:  # noqa: BLE001
            pass
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}
    finally:
        if own and db is not None:
            db.close()


def _run(db, now, rule, override) -> dict:
    rv = rule_version(rule)
    window_start = now - timedelta(minutes=rule.max_age_min)
    groups = (
        db.query(S.sport, S.event_id, S.market)
        .filter(
            S.market.like("player\\_%", escape="\\"),
            S.line.isnot(None),
            S.commence_time > now,
            # game_date (US Eastern date of the start) leads ix_odds_snap_lookup: a range scan
            # instead of reading the whole table every 10 minutes.
            S.game_date >= (now - timedelta(days=1)).date(),
            S.first_seen_at <= now,
            S.last_seen_at >= window_start,
        )
        .distinct()
        .all()
    )
    stats = {"times": 0, "new": 0, "updated": 0, "by_tier": {}}
    out = {"status": "ok", "rule_version": rv, "groups": len(groups)}
    if not groups:
        cut = now - timedelta(hours=RECENT_HOURS)
        recent = db.query(func.count(S.id)).filter(S.last_seen_at >= cut).scalar()
        out.update(times=0, new=0, updated=0, by_tier={}, recent_snapshots=bool(recent))
        return out
    wcache: dict = {}
    for key in sorted(groups):
        rows = (
            db.query(S)
            .filter(S.event_id == key[1], S.market == key[2], S.first_seen_at <= now)
            .all()
        )
        try:
            _group_flags(
                db, key, rows, now, window_start, rule, rv, wcache, override, stats
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            log.warning("fair_price shadow: integrity error for %s, skipped", key)
    out.update(stats)
    return out
