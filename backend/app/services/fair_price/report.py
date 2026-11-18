"""Fair-price shadow report: the review section behind docs/fair-price-shadow-decision.md.

Read-only. Every number is the backtest's own (score_row, clustered_mean, wilson,
_verdict_block); samples follow the pre-registered rule: primary = tier primary, not a close
flag, graded hit/miss/push, ordered by (observed_at, id), rule version shadow.RULE_VERSION.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, inspect

from app.models.predictions_models import FairPriceShadowFlag as F
from app.models.predictions_models import OddsLineSnapshot as S
from app.services import odds_math
from app.services.fair_price import backtest, shadow

DECISION_N = 300
DECISION_DATES = 30  # fp-shadow-v2: the sample also needs this many game dates
ROI_N = 3000
H2_EXCLUDED_BOOK = "espnbet"
STALE_HOURS = 36
GRADED = ("hit", "miss", "push")
VOID = ("dnp", "ungraded")
_WIN = {"hit": True, "miss": False, "push": None}


def _round(x):
    if isinstance(x, float):
        return round(x, 6)
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_round(v) for v in x]
    return x


def _rec(f) -> dict:
    b = f.baseline or {}
    return {
        "id": f.id,
        "observed_at": f.observed_at,
        "tier": f.tier,
        "market": f.market,
        "book": f.book,
        "event_id": f.event_id,
        "player_key": f.player_key,
        "game_date": f.game_date,
        "price": f.price,
        "ev": f.ev,
        "clv": f.clv,
        "win": _WIN.get(f.result),
        "result": f.result,
        "is_close": f.is_close,
        "hours_before": f.hours_before,
        "next_at": f.next_at,
        "next_playable": f.next_playable,
        "rand_price": b.get("price"),
        "rand_clv": b.get("clv"),
        "rand_win": b.get("win"),
    }


def _views(fs):
    return [backtest._view(f) for f in fs]


def _roi_stage(fs: list[dict]) -> str:
    n = len(fs)
    if n < ROI_N:
        return f"pending ({n}/{ROI_N})"
    r = backtest.score_row(_views(fs[:ROI_N]), clv=False)
    if r["roi_lo"] is not None and r["roi_lo"] > 0:
        return "PROFITABLE"
    if r["roi_hi"] is not None and r["roi_hi"] < 0:
        return "UNPROFITABLE"
    return "not distinguishable from break-even"


def _decision_size(fs: list[dict]) -> int | None:
    """Length of the decision sample: the shortest prefix with DECISION_N flags on
    DECISION_DATES game dates. None while it is still open."""
    dates: set = set()
    for i, f in enumerate(fs, 1):
        dates.add(f["game_date"])
        if i >= DECISION_N and len(dates) >= DECISION_DATES:
            return i
    return None


def _sample(fs: list[dict]) -> dict:
    n = len(fs)
    n_dates = len({f["game_date"] for f in fs})
    size = _decision_size(fs)
    out = {
        "n": n,
        "progress": (
            f"{min(n, DECISION_N)}/{DECISION_N} flags, "
            f"{min(n_dates, DECISION_DATES)}/{DECISION_DATES} game dates"
        ),
        "progress_roi": f"{min(n, ROI_N)}/{ROI_N}",
        "all": backtest.score_row(_views(fs)),
        "roi_stage": _roi_stage(fs),
    }
    if size is None:
        out["verdict"] = f"pending ({out['progress']})"
        return out
    first = fs[:size]
    blk = backtest._verdict_block(first, backtest.Params())
    out.update(
        verdict=blk["verdict"],
        decision=blk["primary"],
        random=blk["random"],
        paired_clv_diff=blk["paired_clv_diff"],
        placebo=blk["placebo"],
    )
    return out


def _by(fs: list[dict], key, *, clv=True) -> dict:
    groups: dict = {}
    for f in fs:
        k = key(f)
        if k is not None:
            groups.setdefault(k, []).append(f)
    return {
        k: backtest.score_row(_views(v), clv=clv) for k, v in sorted(groups.items())
    }


def _hours(f):
    h = f["hours_before"]
    if h is None:
        return None
    for lo, hi in backtest.HOUR_BUCKETS:
        if lo <= h < hi:
            return f"{lo}h+" if hi == float("inf") else f"{lo}-{hi}h"
    return None


def _counts(rows: list[F], rule_rows: list[F]) -> dict:
    def block(rs):
        prim = [r for r in rs if r.tier == "primary"]
        mk: dict = {}
        for r in prim:
            mk[r.market] = mk.get(r.market, 0) + 1
        return {
            "flags": len(rs),
            "primary": len(prim),
            "secondary": len(rs) - len(prim),
            "primary_by_market": dict(sorted(mk.items())),
            "graded": sum(r.result in GRADED for r in rs),
            "void": sum(r.result in VOID for r in rs),
            "pending": sum(r.result is None for r in rs),
            "close_flags": sum(bool(r.is_close) for r in rs),
        }

    return {"to_date": block(rows), "yesterday": block(rule_rows)}


def _freshness(db, today: date) -> dict:
    ref = datetime.combine(today, time(23, 59, 59))
    last = db.query(func.max(S.last_seen_at)).scalar()
    nba = db.query(func.max(S.last_seen_at)).filter(S.sport == backtest.SPORT).scalar()
    return {
        "latest_snapshot": last.isoformat() if last else None,
        "latest_nba_snapshot": nba.isoformat() if nba else None,
        "stale": last is None or last < ref - timedelta(hours=STALE_HOURS),
    }


def section(
    db, today: date, start: date | None = None, end: date | None = None
) -> dict:
    if not inspect(db.get_bind()).has_table(F.__tablename__):
        return {"note": "no fair-price shadow table"}
    fresh = _freshness(db, today)
    q = db.query(F)
    if start:
        q = q.filter(F.game_date >= start)
    if end:
        q = q.filter(F.game_date <= end)
    allrows = q.all()
    rows = [r for r in allrows if r.rule_version == shadow.RULE_VERSION]
    yday = today - timedelta(days=1)
    out: dict = {
        "freshness": fresh,
        "rule_version": shadow.RULE_VERSION,
        "other_rule_versions": len(allrows) - len(rows),
        "counts": _counts(rows, [r for r in rows if r.game_date == yday]),
    }
    if fresh["stale"] or not allrows:
        since = fresh["latest_snapshot"] or "ever"
        out["note"] = (
            f"no recent odds snapshots since {since}: zero flags is not a result"
            if fresh["stale"]
            else "no fair-price flags yet: zero flags is not a result"
        )
    prim = sorted(
        (
            _rec(r)
            for r in rows
            if r.tier == "primary" and not r.is_close and r.result in GRADED
        ),
        key=lambda f: (f["observed_at"], f["id"]),
    )
    out["primary"] = _sample(prim)
    out["h2"] = _sample([f for f in prim if f["book"] != H2_EXCLUDED_BOOK])
    close = [
        _rec(r)
        for r in rows
        if r.tier == "primary" and r.is_close and r.result in GRADED
    ]
    out["close_flags"] = backtest.score_row(_views(close), clv=False)
    out["by_book"] = _by(prim, lambda f: f["book"])
    out["by_hours"] = _by(prim, _hours)
    sec = [
        _rec(r)
        for r in rows
        if r.tier == "secondary" and (r.result in GRADED or r.clv is not None)
    ]
    out["secondary_by_market"] = _by(sec, lambda f: f["market"])
    nxt = [f for f in prim if f["next_at"] is not None]
    out["flag_life"] = {
        "with_next": len(nxt),
        "next_playable": sum(bool(f["next_playable"]) for f in nxt),
        "no_later_snapshot": len(prim) - len(nxt),
    }
    cv = [f for f in prim if f["clv"] is not None]
    out["clv_roi_check"] = {
        "n": len(cv),
        "implied_roi": (
            sum(f["clv"] * odds_math.american_to_decimal(f["price"]) for f in cv)
            / len(cv)
            if cv
            else None
        ),
        "realised_roi": out["primary"]["all"]["roi"],
    }
    return _round(
        {**out, "start": start and start.isoformat(), "end": end and end.isoformat()}
    )


# ----------------------------------------------------------------------------- render


def _p(v, signed=False):
    return "n/a" if v is None else (f"{v * 100:+.1f}" if signed else f"{v * 100:.1f}")


def _ci(lo, hi, f=_p):
    return "" if lo is None else f" [{f(lo, True)}, {f(hi, True)}]"


def _row_line(label: str, r: dict) -> str:
    units = None
    if r.get("roi") is not None:
        units = r["roi"] * r["decided"]
    hit = (
        f", hit {_p(r['hit_rate'])}% ({r['hits']}/{r['decided']}) "
        f"Wilson [{_p(r['hit_lo'])}, {_p(r['hit_hi'])}]"
        if r["decided"]
        else ""
    )
    clv = (
        f", CLV {_p(r['clv_mean'], True)}pt{_ci(r['clv_lo'], r['clv_hi'])} (n={r['clv_n']})"
        if r["clv_n"]
        else ""
    )
    roi = (
        f", {units:+.1f}u, ROI {_p(r['roi'], True)}%{_ci(r['roi_lo'], r['roi_hi'])}"
        if units is not None
        else ""
    )
    return f"  {label}: n={r['n']}{clv}{hit}{roi}"


def _sample_lines(name: str, s: dict) -> list[str]:
    L = [f"  {name}: {s['progress']} to decision, {s['progress_roi']} to ROI stage"]
    L.append(_row_line("    graded so far", s["all"]))
    L.append(f"    verdict: {s['verdict']}")
    if "decision" in s:
        L.append(_row_line("    decision sample", s["decision"]))
        L.append(_row_line("    random baseline", s["random"]))
        d = s["paired_clv_diff"]
        if d["mean"] is not None:
            L.append(
                f"    paired CLV diff {_p(d['mean'], True)}pt{_ci(d['lo'], d['hi'])}"
            )
        p = s["placebo"]
        if p:
            L.append(
                f"    placebo ROI {_p(p['mean_roi'], True)}% vs coin-flip "
                f"{_p(p['expectation'], True)}% ({p['runs']} runs)"
            )
    L.append(f"    ROI stage: {s['roi_stage']}")
    return L


def render(sec: dict) -> list[str]:
    if "freshness" not in sec:
        return [f"  {sec.get('note', 'no data')}"]
    L = []
    if sec.get("note"):
        L.append(f"  NOTE: {sec['note']}")
    fr = sec["freshness"]
    L.append(
        f"  snapshots: latest {fr['latest_snapshot']}, NBA {fr['latest_nba_snapshot']}"
        f"{' (STALE)' if fr['stale'] else ''}; rule {sec['rule_version']}"
        + (
            f"; {sec['other_rule_versions']} flags of other rule versions not counted"
            if sec["other_rule_versions"]
            else ""
        )
    )
    for k, label in (("yesterday", "yesterday"), ("to_date", "to date")):
        c = sec["counts"][k]
        mk = ", ".join(f"{m} {n}" for m, n in c["primary_by_market"].items())
        L.append(
            f"  flags {label}: {c['flags']} (primary {c['primary']}"
            f"{' [' + mk + ']' if mk else ''}, secondary {c['secondary']}); "
            f"graded {c['graded']}, void {c['void']}, pending {c['pending']}, "
            f"close {c['close_flags']}"
        )
    L += _sample_lines("primary", sec["primary"])
    L += _sample_lines("H2 (excl. espnbet)", sec["h2"])
    cf = sec["close_flags"]
    if cf["n"]:
        L.append(_row_line("close flags (ROI only)", cf))
    for title, key in (
        ("by book", "by_book"),
        ("by hours before start", "by_hours"),
        ("secondary by market", "secondary_by_market"),
    ):
        if sec[key]:
            L.append(f"  {title}:")
            L += [_row_line("   " + k, r) for k, r in sec[key].items()]
    fl = sec["flag_life"]
    if fl["with_next"]:
        L.append(
            f"  flag life: {fl['next_playable']}/{fl['with_next']} still playable at the "
            f"next snapshot; {fl['no_later_snapshot']} without a later snapshot"
        )
    x = sec["clv_roi_check"]
    if x["n"]:
        L.append(
            f"  CLV->ROI check: implied {_p(x['implied_roi'], True)}% vs realised "
            f"{_p(x['realised_roi'], True)}% (n={x['n']})"
        )
    return L
