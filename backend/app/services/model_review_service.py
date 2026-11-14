"""
Daily model review: one owner-readable report on how the YetAI Bets and the
projections behind them are doing.

``build_review(db, today)`` -> JSON-safe dict; ``render_text`` / ``render_html``
format it. Every section is built independently: a missing/empty table shows
"unavailable: <err>" instead of sinking the report.

Numbers come from the existing loaders: record_gate.load_records (bet + projection
records, withheld keys), the accuracy services' row merges and accuracy_shared
counters, and totals_baseline (NBA totals gate / published bias).
"""

import html
import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.database_models import BetType, YetAIBet
from app.services.accuracy_shared import (
    edge_play_graded_counts,
    ou_call_graded_counts,
)
from app.services.auto_pick import record_gate
from app.services.auto_pick.candidate import EASTERN
from app.services.auto_pick.context_builder import _normalize_sport

log = logging.getLogger(__name__)

BET_WINDOWS = (7, 30, 90)
MODEL_WINDOW_DAYS = 30
BREAKEVEN = 0.5238  # 52.38% at -110
STUCK_HOURS = 24
MISS_LIMIT = 10
VOID_LIMIT = 20
DISAGREE_LIMIT = 25
WITHHELD_LIMIT = 20
SPORTS = ("NBA", "NFL", "NHL")


# ---------- row loaders: normalised {proj, line, actual, pick, correct, label, ident} ----------

# kind "ou": hit = pick vs line vs actual; "edge": hit = stored correct flag.
Loaded = dict[record_gate.RecordKey, tuple[str, list[dict]]]


def _norm(v: Any) -> str:
    return str(v)[:10] if isinstance(v, (date, datetime)) else str(v)


def _row(proj, line, actual, pick, ident, label, correct=None) -> dict:
    return {
        "proj": proj,
        "line": line,
        "actual": actual,
        "pick": pick,
        "correct": correct,
        "label": label,
        "ident": tuple(_norm(i) for i in ident),
    }


def _nba_props(db, start, end) -> Loaded:
    from app.models import predictions_models as pm
    from app.services.nba_accuracy_service import _nba_season_window_rows

    stats = {
        "points_ou": ("points", "projected_points", "actual_points", pm.PointsProjections),
        "three_pt_ou": (
            "threes", "projected_three_pt_made", "actual_three_pt_made",
            pm.ThreePointProjections,
        ),
        "steals_ou": ("steals", "projected_steals", "actual_steals", pm.StealsProjections),
        "assists_ou": (
            "assists", "projected_assists", "actual_assists", pm.AssistsProjections
        ),
        "rebounds_ou": (
            "rebounds", "projected_rebounds", "actual_rebounds", pm.ReboundsProjections
        ),
    }
    out: Loaded = {}
    for part, _label, rows, _merge in _nba_season_window_rows(db, start=start, end=end):
        stat, pf, af, cls = stats[part]
        out[("NBA", "player_prop", stat)] = (
            "ou",
            [
                _row(
                    r.get(pf), r.get("fanduel_line"), r.get(af),
                    r.get("fanduel_over_under"),
                    (cls.__tablename__, r["date"], r["player_id"]),
                    r.get("player_name") or f"player {r['player_id']}",
                )
                for r in rows
            ],
        )
    return out


def _nba_totals(db, start, end) -> Loaded:
    from app.models.predictions_models import NBATotalsActuals, NBATotalsProjections
    from app.services.etl.nba.totals_baseline import CALIBRATION_START, MIN_EDGE

    rows = (
        db.query(NBATotalsActuals)
        .filter(
            NBATotalsActuals.game_date >= max(start, CALIBRATION_START),
            NBATotalsActuals.game_date <= end,
        )
        .all()
    )
    table = NBATotalsProjections.__tablename__
    out = []
    for r in rows:
        edge = (
            r.projected_total - r.market_total
            if r.projected_total is not None and r.market_total
            else None
        )
        # Same would-be call as totals_baseline.pick_record (sign of edge >= MIN_EDGE).
        pick = (
            "over" if edge is not None and edge >= MIN_EDGE
            else "under" if edge is not None and edge <= -MIN_EDGE else None
        )
        out.append(
            _row(
                r.projected_total, r.market_total, r.actual_total, pick,
                (table, r.game_date, r.home_team_name, r.away_team_name),
                f"{r.away_team_name} @ {r.home_team_name}",
            )
        )
    return {("NBA", "total", None): ("ou", out)}


def _spread_rows(projs, merged) -> list[dict]:
    return [
        _row(
            m["projected_margin"],
            None if m["market_spread_home"] is None else -m["market_spread_home"],
            m["actual_margin"], m["recommendation"],
            (p.__table__.name, p.game_date, p.home_team_name, p.away_team_name),
            f"{p.away_team_name} @ {p.home_team_name}",
            correct=m["spread_correct"],
        )
        for p, m in zip(projs, merged)
    ]


def _nba_spread(db, start, end) -> Loaded:
    from app.models.predictions_models import NBASpreadActuals, NBASpreadProjections
    from app.services.nfl_accuracy_service import _merge_actuals_spread

    def q(model):
        return (
            db.query(model)
            .filter(model.game_date >= start, model.game_date <= end)
            .all()
        )

    projs = q(NBASpreadProjections)
    merged = _merge_actuals_spread(projs, q(NBASpreadActuals))
    return {("NBA", "spread", None): ("edge", _spread_rows(projs, merged))}


def _nhl(db, start, end) -> Loaded:
    from app.models.predictions_models import (
        NHLGoalieActuals,
        NHLGoaliePredictions,
        NHLTeamTotalsActuals,
        NHLTeamTotalsPredictions,
    )
    from app.services.nhl_accuracy_service import _parse_pick

    def q(model):
        return (
            db.query(model)
            .filter(model.game_date >= start, model.game_date <= end)
            .all()
        )

    goalie_act = {a.goalie_id: a for a in q(NHLGoalieActuals)}
    goalies = []
    for p in q(NHLGoaliePredictions):
        a = goalie_act.get(p.goalie_id)
        goalies.append(
            _row(
                p.predicted_saves, p.saves_line, a.actual_saves if a else None,
                _parse_pick(p.betting_recommendation),
                (p.__table__.name, p.game_date, p.goalie_id), p.goalie_name,
            )
        )
    tot_act = {(a.home_team_name, a.away_team_name): a for a in q(NHLTeamTotalsActuals)}
    totals = []
    for p in q(NHLTeamTotalsPredictions):
        a = tot_act.get((p.home_team_name, p.away_team_name))
        totals.append(
            _row(
                p.predicted_total_goals, p.draftkings_ou_line,
                a.actual_total_goals if a else None,
                _parse_pick(p.betting_recommendation),
                (p.__table__.name, p.game_date, p.home_team_id, p.away_team_id),
                f"{p.away_team_name} @ {p.home_team_name}",
            )
        )
    return {
        ("NHL", "player_prop", "saves"): ("ou", goalies),
        ("NHL", "total", None): ("ou", totals),
    }


def _nfl(db, start, end) -> Loaded:
    from app.models.predictions_models import (
        NFLSpreadActuals,
        NFLSpreadProjections,
        NFLTotalsActuals,
        NFLTotalsProjections,
        QBActuals,
        QBPredictions,
        RecvYdsActuals,
        RecvYdsPredictions,
    )
    from app.services.nfl_accuracy_service import (
        _game_date_only,
        _merge_actuals_qb_range,
        _merge_actuals_spread,
        _merge_actuals_totals,
    )

    def q(model):
        return (
            db.query(model)
            .filter(
                func.date(model.game_date) >= start, func.date(model.game_date) <= end
            )
            .all()
        )

    qb_p = q(QBPredictions)
    qb = [
        _row(
            m["predicted_passing_yards"], m["ou_line"], m["actual_passing_yards"],
            m["betting_recommendation"],
            (p.__table__.name, _game_date_only(p.game_date), p.qb_player_id),
            f"QB {p.qb_player_id}",
        )
        for p, m in zip(qb_p, _merge_actuals_qb_range(qb_p, q(QBActuals)))
    ]
    recv_act = {(a.player_id, a.game_date): a for a in q(RecvYdsActuals)}
    recv = []
    for p in q(RecvYdsPredictions):
        a = recv_act.get((p.player_id, p.game_date))
        recv.append(
            _row(
                p.predicted_receiving_yards, p.ou_line,
                a.actual_receiving_yards if a else None, p.betting_recommendation,
                (p.__table__.name, p.game_date, p.player_id), p.player_name,
            )
        )
    sp_p = q(NFLSpreadProjections)
    spread = _spread_rows(sp_p, _merge_actuals_spread(sp_p, q(NFLSpreadActuals)))
    tot_p = q(NFLTotalsProjections)
    totals = [
        _row(
            m["projected_total"], m["market_total"], m["actual_total"],
            m["recommendation"],
            (p.__table__.name, p.game_date, p.home_team_name, p.away_team_name),
            f"{p.away_team_name} @ {p.home_team_name}",
        )
        for p, m in zip(tot_p, _merge_actuals_totals(tot_p, q(NFLTotalsActuals)))
    ]
    return {
        ("NFL", "player_prop", "passing_yards"): ("ou", qb),
        ("NFL", "player_prop", "receiving_yards"): ("ou", recv),
        ("NFL", "spread", None): ("edge", spread),
        ("NFL", "total", None): ("ou", totals),
    }


LOADERS: tuple[Callable[..., Loaded], ...] = (
    _nba_props, _nba_totals, _nba_spread, _nhl, _nfl,
)


def load_rows(db: Session, start: date, end: date) -> Loaded:
    """All sports' normalised rows for [start, end]; a failing loader is skipped."""
    out: Loaded = {}
    for fn in LOADERS:
        try:
            out.update(fn(db, start, end))
        except Exception:
            log.exception("model_review: loader %s failed", fn.__name__)
            db.rollback()
    return out


# ---------- maths ----------


def _mean(xs: list[float]) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def _r(v: Optional[float], nd: int = 2) -> Optional[float]:
    return None if v is None else round(v, nd)


def row_grade(kind: str, row: dict) -> Optional[bool]:
    """Did the projection's own call win vs the line? None = no call / push / ungraded."""
    if row["actual"] is None:
        return None
    if kind == "edge":
        return row["correct"] if (row["pick"] or "").upper() in ("HOME", "AWAY") else None
    pick = (row["pick"] or "").strip().lower()
    if pick not in ("over", "o", "under", "u") or row["line"] is None:
        return None
    if float(row["actual"]) == float(row["line"]):
        return None
    over = pick in ("over", "o")
    return (float(row["actual"]) > float(row["line"])) == over


def stats(kind: str, rows: list[dict]) -> dict:
    if kind == "edge":
        hits, graded = edge_play_graded_counts(
            rows, pick_field="pick", correct_field="correct"
        )
    else:
        hits, graded = ou_call_graded_counts(
            rows, line_field="line", pick_field="pick", actual_field="actual"
        )
    scored = [r for r in rows if r["proj"] is not None and r["actual"] is not None]
    errs = [float(r["proj"]) - float(r["actual"]) for r in scored]
    line_errs = [
        abs(float(r["line"]) - float(r["actual"])) for r in scored if r["line"] is not None
    ]
    return {
        "graded": graded,
        "hits": hits,
        "hit_rate": _r(hits / graded, 4) if graded else None,
        "n": len(errs),
        "bias": _r(_mean(errs)),
        "mae": _r(_mean([abs(e) for e in errs])),
        "line_mae": _r(_mean(line_errs)),
    }


# ---------- sections ----------


def _day_start_utc(d: date) -> datetime:
    """Start of ET day ``d`` as naive UTC (DB timestamps are naive UTC)."""
    return (
        datetime.combine(d, time.min, tzinfo=EASTERN)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )


def _empty_rec() -> dict:
    return {"picks": 0, "w": 0, "l": 0, "p": 0, "units": 0.0}


def _add(rec: dict, status: str, odds: float) -> None:
    rec["picks"] += 1
    rec[{"won": "w", "lost": "l", "pushed": "p"}[status]] += 1
    if status != "pushed":
        rec["units"] += record_gate.stake_units(odds, status == "won")


def _fin(rec: dict) -> dict:
    return {**rec, "units": round(rec["units"], 2)}


def _bets_section(db: Session, today: date) -> dict:
    start_today, end = _day_start_utc(today), _day_start_utc(today + timedelta(days=1))
    windows = {}
    for days in BET_WINDOWS:
        rows = (
            db.query(YetAIBet)
            .filter(
                YetAIBet.status.in_(["won", "lost", "pushed"]),
                YetAIBet.settled_at >= start_today - timedelta(days=days),
                YetAIBet.settled_at < end,
            )
            .all()
        )
        total, parlays = _empty_rec(), _empty_rec()
        by_sport, by_market = defaultdict(_empty_rec), defaultdict(_empty_rec)
        for b in rows:
            if b.bet_type == BetType.PARLAY:
                _add(parlays, b.status, b.odds)
                continue  # parlay units are not comparable to straight bets
            _add(total, b.status, b.odds)
            _add(by_sport[_normalize_sport(str(b.sport or "unknown"))], b.status, b.odds)
            _add(by_market[b.bet_type.value], b.status, b.odds)
        windows[str(days)] = {
            **_fin(total),
            "parlays": {k: parlays[k] for k in ("picks", "w", "l", "p")},
            "by_sport": {k: _fin(v) for k, v in sorted(by_sport.items())},
            "by_market": {k: _fin(v) for k, v in sorted(by_market.items())},
        }
    now = min(datetime.utcnow(), end)  # a past review date is judged as of that day
    stuck = (
        db.query(YetAIBet)
        .filter(
            YetAIBet.status.in_(["active", "pending"]),
            YetAIBet.commence_time < now - timedelta(hours=STUCK_HOURS),
        )
        .count()
    )
    voids = (
        db.query(YetAIBet)
        .filter(
            YetAIBet.status == "void",
            YetAIBet.settled_at >= start_today - timedelta(days=30),
            YetAIBet.settled_at < end,
        )
        .order_by(YetAIBet.settled_at.desc())
        .all()
    )
    return {
        "windows": windows,
        "pending_too_long": stuck,
        "voids_30d": {
            "count": len(voids),
            "rows": [
                {"id": b.id, "title": b.title, "result": b.result}
                for b in voids[:VOID_LIMIT]
            ],
        },
    }


def _projection_section(cur: Loaded, prior: Loaded) -> list[dict]:
    out = []
    for key in sorted(cur, key=lambda k: tuple(p or "" for p in k)):
        kind, rows = cur[key]
        s = stats(kind, rows)
        if not s["n"]:
            continue
        p = stats(kind, prior.get(key, (kind, []))[1])
        out.append(
            {
                "key": record_gate.key_label(key),
                "league": key[0],
                **s,
                "breakeven": BREAKEVEN,
                "prior": p,
                "hit_rate_trend": (
                    _r(s["hit_rate"] - p["hit_rate"], 4)
                    if s["hit_rate"] is not None and p["hit_rate"] is not None
                    else None
                ),
                "mae_trend": (
                    _r(s["mae"] - p["mae"])
                    if s["mae"] is not None and p["mae"] is not None
                    else None
                ),
            }
        )
    return out


def _gate_section(db: Session, today: date) -> dict:
    from app.services.etl.nba import totals_baseline as tb
    from app.models.predictions_models import NBATotalsActuals

    now = _day_start_utc(today) + timedelta(hours=12)  # same ET date for the gate
    records = record_gate.load_records(db, now)
    withheld = sorted(
        (r for r in records.values() if r.withheld), key=lambda r: r.shrunk_roi
    )
    out: dict[str, Any] = {
        "enabled": record_gate.gate_enabled(),
        "keys_tracked": len(records),
        "withheld": [
            {
                "key": record_gate.key_label(r.key),
                "n_eff": round(r.n_eff, 1),
                "shrunk_roi": round(r.shrunk_roi, 4),
                "bet_n": r.bet_n,
                "bet_units": round(r.bet_units, 2),
                "proj_n": r.proj_n,
                "proj_hits": r.proj_hits,
            }
            for r in withheld[:WITHHELD_LIMIT]
        ],
    }
    try:
        rows = (
            db.query(NBATotalsActuals)
            .filter(
                NBATotalsActuals.game_date >= max(tb.CALIBRATION_START, today - timedelta(days=60)),
                NBATotalsActuals.game_date < today,
            )
            .all()
        )
        record = tb.pick_record(rows)
        rec, conf, note = tb.recommend(tb.MIN_EDGE + 1, record)  # a qualifying edge
        out["nba_totals"] = {
            "hits": record[0],
            "picks": record[1],
            "calls_published": rec != "NO_PLAY",
            "note": note,
            "confidence": conf,
        }
    except Exception as e:
        db.rollback()
        out["nba_totals"] = {"unavailable": f"{type(e).__name__}: {e}"}
    try:
        from app.services.etl.nba import totals_projector as tp

        points, n = tb.published_bias(tp._load_published_history(today, db), today)
        out["nba_totals_bias"] = {
            "points": round(points, 2),
            "games": n,
            "enabled": tp.published_bias_enabled(),
        }
    except Exception as e:
        db.rollback()
        out["nba_totals_bias"] = {"unavailable": f"{type(e).__name__}: {e}"}
    return out


def _misses_section(db: Session, today: date, cur: Loaded) -> dict:
    day = today - timedelta(days=1)
    rows = []
    for key, (kind, rs) in load_rows(db, day, day).items():
        mae = stats(kind, cur.get(key, (kind, []))[1])["mae"]
        for r in rs:
            if r["proj"] is None or r["actual"] is None:
                continue
            err = float(r["proj"]) - float(r["actual"])
            rows.append(
                {
                    "key": record_gate.key_label(key),
                    "who": r["label"],
                    "projection": _r(float(r["proj"])),
                    "line": r["line"],
                    "actual": r["actual"],
                    "error": _r(err),
                    # error in units of this key's 30-day MAE, so yards and goals compare
                    "score": abs(err) / mae if mae else abs(err),
                }
            )
    rows.sort(key=lambda m: m["score"], reverse=True)
    for m in rows:
        m["score"] = _r(m["score"])
    return {"date": day.isoformat(), "rows": rows[:MISS_LIMIT]}


def _disagreements_section(db: Session, today: date, cur: Loaded) -> dict:
    index = {r["ident"]: (kind, r) for kind, rs in cur.values() for r in rs}
    start_today, end = _day_start_utc(today), _day_start_utc(today + timedelta(days=1))
    bets = (
        db.query(YetAIBet)
        .filter(
            YetAIBet.status.in_(["won", "lost"]),
            YetAIBet.settled_at >= start_today - timedelta(days=MODEL_WINDOW_DAYS),
            YetAIBet.settled_at < end,
        )
        .all()
    )
    rows, no_ref, unmatched, skipped = [], 0, 0, 0
    checked = 0
    for b in bets:
        if b.bet_type in (BetType.PARLAY, BetType.MONEYLINE):
            skipped += 1  # no O/U or spread call to compare with
            continue
        pf = b.prediction_factors if isinstance(b.prediction_factors, dict) else {}
        ref = pf.get("projection_ref")
        if not isinstance(ref, dict):
            no_ref += 1
            continue
        found = _lookup(index, ref)
        if not found:
            unmatched += 1
            continue
        kind, proj = found
        grade = row_grade(kind, proj)
        if grade is None:
            unmatched += 1
            continue
        checked += 1
        if grade != (b.status == "won"):
            rows.append(
                {
                    "bet_id": b.id,
                    "title": b.title,
                    "bet_result": b.status,
                    "projection": proj["label"],
                    "projection_call": proj["pick"],
                    "projection_graded": "won" if grade else "lost",
                    "line": proj["line"],
                    "actual": proj["actual"],
                    "ref": f'{ref.get("table")}#{ref.get("id")}',
                }
            )
    return {
        "window_days": MODEL_WINDOW_DAYS,
        "checked": checked,
        "disagreements": len(rows),
        "rows": rows[:DISAGREE_LIMIT],
        "without_projection_ref": no_ref,
        "unmatched_or_ungraded": unmatched,
        "skipped_parlay_or_moneyline": skipped,
    }


def _lookup(index: dict, ref: dict):
    """Find the projection row for a bet's projection_ref by its key columns.

    Keys, not the row id: snapshot rewrites delete/re-insert rows, so the id may be
    gone while the (table, date, entity) key still identifies the surviving row."""
    table = ref.get("table")
    d = ref.get("game_date") or ref.get("date")
    if not table or d is None:
        return None
    for entity in (
        (ref.get("home_team_name"), ref.get("away_team_name")),
        (ref.get("player_id"),),
        (ref.get("qb_player_id"),),
        (ref.get("goalie_id"),),
        (ref.get("home_team_id"), ref.get("away_team_id")),
    ):
        if all(e is not None for e in entity):
            ident = (table, _norm(d), *(_norm(e) for e in entity))
            if ident in index:
                return index[ident]
    return None


def _versions_section(db: Session, today: date) -> dict:
    from app.models import predictions_models as pm

    since = _day_start_utc(today) - timedelta(days=MODEL_WINDOW_DAYS)
    bets = dict(
        db.query(YetAIBet.model_version, func.count())
        .filter(YetAIBet.created_at >= since)
        .group_by(YetAIBet.model_version)
        .all()
    )
    tables: dict[str, dict] = {}
    day0 = today - timedelta(days=MODEL_WINDOW_DAYS)
    for name in dir(pm):
        cls = getattr(pm, name)
        if not (isinstance(cls, type) and hasattr(cls, "__tablename__")):
            continue
        mv = getattr(cls, "model_version", None)
        dcol = getattr(cls, "game_date", None) or getattr(cls, "date", None)
        if mv is None or dcol is None or not cls.__tablename__.startswith("pred_"):
            continue
        try:
            got = dict(
                db.query(mv, func.count()).filter(dcol >= day0).group_by(mv).all()
            )
        except Exception:
            db.rollback()
            continue
        if got:
            tables[cls.__tablename__] = {str(k): v for k, v in got.items()}
    return {
        "bets_30d": {str(k): v for k, v in bets.items()},
        "projection_tables": tables,
    }


def _clv_section(db: Session) -> dict:
    """Closing lines: nothing writes OddsHistory and no *_closing* column exists on any
    projection / line table (game-lines rows are overwritten by the updaters), so there
    is no stored close to measure auto bets against."""
    from app.models.sports_models import OddsHistory

    try:
        n = db.query(func.count(OddsHistory.id)).scalar() or 0
    except Exception:  # table absent: still no stored close
        db.rollback()
        n = None
    return {
        "stored": False,
        "sports": list(SPORTS),
        "odds_history_rows": n,
        "note": f"CLV: closing lines are not stored for {', '.join(SPORTS)}",
    }


# ---------- build ----------


def _safe(db: Session, fn: Callable[..., Any], *args) -> Any:
    try:
        return fn(*args)
    except Exception as e:
        log.exception("model_review: section %s failed", fn.__name__)
        try:
            db.rollback()
        except Exception:
            pass
        return {"unavailable": f"{type(e).__name__}: {e}"}


def build_review(db: Session, today: date) -> dict:
    cur_start = today - timedelta(days=MODEL_WINDOW_DAYS)
    cur = _safe(db, load_rows, db, cur_start, today - timedelta(days=1))
    prior = _safe(
        db, load_rows, db,
        cur_start - timedelta(days=MODEL_WINDOW_DAYS), cur_start - timedelta(days=1),
    )
    if not isinstance(cur, dict) or "unavailable" in cur:
        cur = {}
    if not isinstance(prior, dict) or "unavailable" in prior:
        prior = {}
    return {
        "date": today.isoformat(),
        "bets": _safe(db, _bets_section, db, today),
        "projections": _safe(db, _projection_section, cur, prior),
        "gate": _safe(db, _gate_section, db, today),
        "misses": _safe(db, _misses_section, db, today, cur),
        "disagreements": _safe(db, _disagreements_section, db, today, cur),
        "model_versions": _safe(db, _versions_section, db, today),
        "clv": _safe(db, _clv_section, db),
    }


# ---------- render ----------


def _pct(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def _num(v: Any, signed: bool = False) -> str:
    if v is None:
        return "n/a"
    return f"{v:+.2f}" if signed else f"{v:.2f}"


def _rec_line(label: str, r: dict) -> str:
    return (
        f"  {label}: {r['picks']} picks, {r['w']}-{r['l']}-{r['p']}, "
        f"{r['units']:+.2f}u"
    )


def _unavailable(sec: Any) -> Optional[str]:
    if isinstance(sec, dict) and "unavailable" in sec:
        return f"  unavailable: {sec['unavailable']}"
    return None


def render_text(review: dict) -> str:
    L: list[str] = [f"YETAI MODEL REVIEW {review['date']}", ""]

    L.append("== YetAI Bets record ==")
    bets = review["bets"]
    if _unavailable(bets):
        L.append(_unavailable(bets))
    else:
        for days, w in bets["windows"].items():
            L.append(_rec_line(f"last {days}d (straight bets)", w))
            p = w["parlays"]
            if p["picks"]:
                L.append(f"    parlays: {p['w']}-{p['l']}-{p['p']}")
            for k, v in w["by_sport"].items():
                L.append("  " + _rec_line(f"{k}", v).strip())
            for k, v in w["by_market"].items():
                L.append("  " + _rec_line(f"[{k}]", v).strip())
        L.append(f"  active bets pending > {STUCK_HOURS}h after start: {bets['pending_too_long']}")
        v = bets["voids_30d"]
        L.append(f"  voids (30d): {v['count']}")
        for r in v["rows"]:
            L.append(f"    {r['id']} {r['title']}: {r['result']}")
    L.append("")

    L.append("== Projection accuracy (last 30d vs prior 30d) ==")
    proj = review["projections"]
    if _unavailable(proj):
        L.append(_unavailable(proj))
    elif not proj:
        L.append("  no graded projections")
    else:
        L.append(f"  breakeven hit rate at -110: {_pct(BREAKEVEN)}")
        for p in proj:
            vs = (
                "" if p["hit_rate"] is None
                else " (above breakeven)" if p["hit_rate"] >= BREAKEVEN
                else " (below breakeven)"
            )
            trend = (
                "" if p["hit_rate_trend"] is None
                else f", hit trend {p['hit_rate_trend'] * 100:+.1f}pt"
            )
            mt = "" if p["mae_trend"] is None else f", MAE trend {p['mae_trend']:+.2f}"
            L.append(
                f"  {p['key']}: {p['hits']}/{p['graded']} calls {_pct(p['hit_rate'])}{vs}; "
                f"bias {_num(p['bias'], True)}, MAE {_num(p['mae'])}, "
                f"line MAE {_num(p['line_mae'])} (n={p['n']}){trend}{mt}"
            )
    L.append("")

    L.append("== Record gate ==")
    g = review["gate"]
    if _unavailable(g):
        L.append(_unavailable(g))
    else:
        L.append(
            f"  gate {'on' if g['enabled'] else 'OFF'}, {g['keys_tracked']} keys tracked, "
            f"{len(g['withheld'])} withheld"
        )
        for w in g["withheld"]:
            L.append(
                f"  WITHHELD {w['key']}: n_eff {w['n_eff']}, shrunk ROI "
                f"{w['shrunk_roi'] * 100:+.1f}% (bets {w['bet_n']} {w['bet_units']:+.2f}u; "
                f"projections {w['proj_hits']}/{w['proj_n']})"
            )
        t = g.get("nba_totals", {})
        if "unavailable" in t:
            L.append(f"  NBA totals gate unavailable: {t['unavailable']}")
        else:
            L.append(
                f"  NBA totals gate: {t['hits']}/{t['picks']}, calls "
                f"{'published' if t['calls_published'] else 'WITHHELD'} ({t['note']})"
            )
        b = g.get("nba_totals_bias", {})
        if "unavailable" in b:
            L.append(f"  NBA totals bias unavailable: {b['unavailable']}")
        else:
            L.append(
                f"  NBA totals published-bias correction: {b['points']:+.2f} pts "
                f"({b['games']} games, {'on' if b['enabled'] else 'off'})"
            )
    L.append("")

    m = review["misses"]
    L.append(f"== Biggest misses {m.get('date', '')} ==")
    if _unavailable(m):
        L.append(_unavailable(m))
    elif not m["rows"]:
        L.append("  none graded yet")
    else:
        for r in m["rows"]:
            L.append(
                f"  {r['who']} [{r['key']}]: proj {r['projection']}, line "
                f"{r['line'] if r['line'] is not None else 'n/a'}, actual {r['actual']} "
                f"(err {r['error']:+.2f}, {r['score']}x MAE)"
            )
    L.append("")

    L.append("== Bet vs projection disagreements (30d) ==")
    d = review["disagreements"]
    if _unavailable(d):
        L.append(_unavailable(d))
    else:
        L.append(
            f"  {d['disagreements']} of {d['checked']} compared; "
            f"{d['without_projection_ref']} bets without projection_ref, "
            f"{d['unmatched_or_ungraded']} unmatched/ungraded, "
            f"{d['skipped_parlay_or_moneyline']} parlay/moneyline skipped"
        )
        for r in d["rows"]:
            L.append(
                f"  {r['bet_id']} {r['title']}: bet {r['bet_result']}, projection "
                f"{r['projection_graded']} ({r['projection']} {r['projection_call']} "
                f"line {r['line']}, actual {r['actual']}) [{r['ref']}]"
            )
    L.append("")

    L.append("== Model versions (30d) ==")
    mv = review["model_versions"]
    if _unavailable(mv):
        L.append(_unavailable(mv))
    else:
        L.append(f"  bets: {mv['bets_30d'] or 'none'}")
        for t, v in mv["projection_tables"].items():
            L.append(f"  {t}: {v}")
    L.append("")

    L.append("== CLV ==")
    c = review["clv"]
    L.append(_unavailable(c) or f"  {c['note']}")
    return "\n".join(L) + "\n"


def render_html(review: dict) -> str:
    return (
        "<html><body><pre style=\"font-family:monospace;font-size:13px\">"
        + html.escape(render_text(review))
        + "</pre></body></html>"
    )
