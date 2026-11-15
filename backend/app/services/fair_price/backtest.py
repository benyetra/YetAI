"""Fair-price backtest: replay snapshots, flag, score CLV / ROI, baselines, verdict.

Loading functions take a SQLAlchemy session and return plain lists/dicts; replay and scoring
are pure functions over those. Design: .factory/edge-engine-plan/brief-t3-backtest.md.
"""

from __future__ import annotations

import csv
import io
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Iterable

from app.services import odds_math
from app.services.fair_price import consensus, flags as fp, lines

Z = 1.96
SPORT = "basketball_nba"

# Verdict rule (do not tune; text identical to the design doc).
MIN_N_GO = 300
MIN_N_ROI_NO_GO = 1000
VERDICT_RULES = {
    "INVALID": "|placebo mean ROI - coin-flip expectation| > 1.96 * se_placebo, or the random "
    "baseline's mean CLV 95% lower bound > 0 (the pipeline is wrong; fix it before reading "
    "results).",
    "GO": "n >= 300 and mean CLV lower bound > 0 and ROI point estimate >= 0 and the paired "
    "difference (flag CLV - its random baseline CLV) has a clustered lower bound > 0.",
    "NO GO": "n >= 300 and mean CLV upper bound <= 0, or n >= 1000 and ROI upper bound < 0.",
    "INCONCLUSIVE": "otherwise.",
}

EDGE_BUCKETS = [(0.05, 0.075), (0.075, 0.10), (0.10, 0.15), (0.15, math.inf)]
HOUR_BUCKETS = [(0, 1), (1, 3), (3, 6), (6, 9), (9, math.inf)]
CAL_METHODS = ("multiplicative", "additive", "power", "shin")
NAME_TABLES = (
    "pred_points_projections",
    "pred_rebounds_projections",
    "pred_assists_projections",
    "pred_three_point_projections",
    "pred_steals_projections",
    "pred_blocks_projections",
    "pred_pra_projections",
    "pred_team_roster",
)
# stat per market: tuple of RecentGames columns summed
MARKET_STAT = {
    "player_rebounds": ("rebounds",),
    "player_assists": ("assists",),
    "player_points": ("points",),
    "player_threes": ("three_pt_made",),
    "player_steals": ("steals",),
    "player_blocks": ("blocks",),
    "player_points_rebounds_assists": ("points", "rebounds", "assists"),
}


@dataclass
class SnapQuote:
    """One OddsLineSnapshot row (duck-types to flags.Q)."""

    event_id: str
    market: str
    player_key: str
    book: str
    line: float | None
    over_price: int | None
    under_price: int | None
    first_seen_at: datetime
    last_seen_at: datetime
    commence_time: datetime | None
    game_date: date | None


@dataclass(frozen=True)
class Params:
    rule: fp.FlagRule = field(default_factory=fp.FlagRule)
    seed: int = 0
    placebo_runs: int = 20
    min_n_weights: int = 300


# ----------------------------------------------------------------------------- loading


def load_snapshots(session, markets, start: date, end: date) -> list[SnapQuote]:
    from app.models.predictions_models import OddsLineSnapshot as S

    rows = (
        session.query(S)
        .filter(
            S.sport == SPORT,
            S.market.in_(list(markets)),
            S.game_date >= start,
            S.game_date <= end,
            S.line.isnot(None),
        )
        .all()
    )
    return [
        SnapQuote(
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
        for r in rows
    ]


def load_player_keys(session) -> tuple[dict[str, int], int]:
    """({player_key: player_id}, keys dropped for mapping to two player_ids)."""
    from sqlalchemy import text

    from app.services.odds_snapshots import player_key

    sql = " UNION ".join(
        f"SELECT player_id, player_name FROM {t} WHERE player_name IS NOT NULL"
        for t in NAME_TABLES
    )
    ids: dict[str, set[int]] = defaultdict(set)
    for pid, name in session.execute(text(sql)):
        k = player_key(name)
        if k:
            ids[k].add(int(pid))
    keep = {k: next(iter(v)) for k, v in ids.items() if len(v) == 1}
    return keep, len(ids) - len(keep)


def load_box(session, start: date, end: date) -> dict[tuple[int, date], dict]:
    from app.models.predictions_models import RecentGames as R

    cols = (
        "minutes",
        "rebounds",
        "assists",
        "points",
        "three_pt_made",
        "steals",
        "blocks",
    )
    out: dict[tuple[int, date], dict] = {}
    q = session.query(R).filter(R.game_date >= start, R.game_date <= end)
    for r in q.order_by(R.id):
        out.setdefault((r.player_id, r.game_date), {c: getattr(r, c) for c in cols})
    return out


# ----------------------------------------------------------------------------- statistics


def _fin(x):
    return None if x is None or not math.isfinite(x) else x


def wilson(hits: int, n: int) -> tuple[float, float] | tuple[None, None]:
    if n == 0:
        return None, None
    p = hits / n
    d = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / d
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return c - h, c + h


def clustered_mean(xs: list[float], groups: list) -> dict:
    """Mean with cluster-robust se = sqrt(G/(G-1) * sum_g (sum_{i in g}(x_i - mean))^2) / n."""
    n = len(xs)
    if n == 0:
        return {"n": 0, "mean": None, "se": None, "lo": None, "hi": None}
    m = sum(xs) / n
    sums: dict = defaultdict(float)
    for x, g in zip(xs, groups):
        sums[g] += x - m
    G = len(sums)
    if G < 2:
        return {"n": n, "mean": m, "se": None, "lo": None, "hi": None}
    se = math.sqrt(G / (G - 1) * sum(v * v for v in sums.values())) / n
    return {"n": n, "mean": m, "se": se, "lo": m - Z * se, "hi": m + Z * se}


def _view(f: dict, prefix: str = "") -> dict:
    """Scoring view of a flag record (prefix 'rand_' for the random baseline)."""
    return {
        "clv": f.get(prefix + "clv"),
        "win": f.get(prefix + "win"),
        "price": f.get(prefix + "price", f["price"]) if prefix else f["price"],
        "ev": f["ev"] if not prefix else None,
        "game_date": f["game_date"],
    }


def score_row(views: list[dict], *, clv: bool = True) -> dict:
    """One scoring-table row from views (clv, win True/False/None, price, ev, game_date)."""
    out: dict = {"n": len(views), "n_dates": len({v["game_date"] for v in views})}
    cv = [v for v in views if clv and v["clv"] is not None]
    c = clustered_mean([v["clv"] for v in cv], [v["game_date"] for v in cv])
    out.update(
        clv_n=c["n"],
        clv_mean=c["mean"],
        clv_se=c["se"],
        clv_lo=c["lo"],
        clv_hi=c["hi"],
        clv_pos_share=(sum(v["clv"] > 0 for v in cv) / len(cv)) if cv else None,
    )
    dec = [v for v in views if v["win"] is not None]
    hits = sum(1 for v in dec if v["win"])
    lo, hi = wilson(hits, len(dec))
    r = clustered_mean(
        [odds_math.units_won(v["price"], v["win"]) for v in dec],
        [v["game_date"] for v in dec],
    )
    evs = [v["ev"] for v in views if v["ev"] is not None]
    out.update(
        decided=len(dec),
        hits=hits,
        hit_rate=hits / len(dec) if dec else None,
        hit_lo=lo,
        hit_hi=hi,
        roi=r["mean"],
        roi_se=r["se"],
        roi_lo=r["lo"],
        roi_hi=r["hi"],
        ev_mean=sum(evs) / len(evs) if evs else None,
        price_median=statistics.median([v["price"] for v in views]) if views else None,
    )
    return out


# ----------------------------------------------------------------------------- verdict


def decide(row: dict, placebo: dict | None, rand_row: dict, paired: dict) -> str:
    """Verdict from the primary row, placebo summary, random-baseline row and paired CLV diff."""
    if placebo and placebo.get("se") is not None:
        if abs(placebo["mean_roi"] - placebo["expectation"]) > Z * placebo["se"]:
            return "INVALID"
    if rand_row.get("clv_lo") is not None and rand_row["clv_lo"] > 0:
        return "INVALID"
    n = row["n"]
    if (
        n >= MIN_N_GO
        and row["clv_lo"] is not None
        and row["clv_lo"] > 0
        and row["roi"] is not None
        and row["roi"] >= 0
        and paired.get("lo") is not None
        and paired["lo"] > 0
    ):
        return "GO"
    if (n >= MIN_N_GO and row["clv_hi"] is not None and row["clv_hi"] <= 0) or (
        n >= MIN_N_ROI_NO_GO and row["roi_hi"] is not None and row["roi_hi"] < 0
    ):
        return "NO GO"
    return "INCONCLUSIVE"


# ----------------------------------------------------------------------------- replay


def _stat(market, pk, gd, key_to_id, box):
    """(stat, void reason)."""
    pid = key_to_id.get(pk)
    if pid is None:
        return None, "no_player"
    r = box.get((pid, gd))
    if r is None:
        return None, "no_box"
    if not r.get("minutes"):
        return None, "no_minutes"
    vals = [r.get(c) for c in MARKET_STAT[market]]
    if any(v is None for v in vals):
        return None, "no_box"
    return float(sum(vals)), None


def _win(stat, line, side):
    """True / False / None (push or void)."""
    if stat is None or stat == line:
        return None
    return (stat > line) if side == "o" else (stat < line)


def _pools(book_probs, weights, market):
    """lazily-cached per target line: ({book: converted p}, sum w*logit, sum w)."""
    cache: dict = {}
    w = weights or {}

    def get(line):
        if line not in cache:
            got: dict[str, float] = {}
            for book, pts in book_probs.items():
                ln, p = min(pts, key=lambda t: (abs(t[0] - line), abs(t[1] - 0.5)))
                conv = lines.convert(p, ln, line, market)
                if conv is not None:
                    got[book] = conv
            s = sum(w.get(b, 1.0) * consensus._logit(p) for b, p in got.items())
            cache[line] = (got, s, sum(w.get(b, 1.0) for b in got))
        return cache[line]

    return get


def fast_prop_flags(quotes, at, market, weights, rule, commence_time=None):
    """evaluate_prop with leave-one-out blends formed from pooled sums (equal up to float
    rounding); each book's conversion to a target line is computed once."""
    probs = fp.book_fair(quotes, at, rule)
    pool = _pools(probs, weights, market)
    w = weights or {}
    expires = at + timedelta(minutes=rule.expiry_min)
    if commence_time is not None:
        expires = min(expires, commence_time)
    out: list[fp.Flag] = []
    for q in quotes:
        if (
            q.book in rule.reference_only
            or q.book in rule.consensus_only
            or not fp._fresh(q, at, rule)
        ):
            continue
        got, s, ws = pool(q.line)
        n = len(got)
        if q.book in got:
            s -= w.get(q.book, 1.0) * consensus._logit(got[q.book])
            ws -= w.get(q.book, 1.0)
            n -= 1
        if n == 0 or n < rule.min_books:
            continue
        fair = 1 / (1 + math.exp(-s / ws))
        for side, price, p in (
            ("o", q.over_price, fair),
            ("u", q.under_price, 1 - fair),
        ):
            if not price or not rule.p_range[0] <= p <= rule.p_range[1]:
                continue
            e = fp.ev(p, price)
            if e >= rule.min_ev:
                out.append(
                    fp.Flag(
                        q.book,
                        side,
                        q.line,
                        int(price),
                        p,
                        e,
                        fp.playable_to(p, rule.playable_min_ev),
                        n,
                        at,
                        expires,
                    )
                )
    return out


def _present(quotes, t):
    return [q for q in quotes if q.first_seen_at <= t <= q.last_seen_at]


def _group(quotes):
    """{(event, market): {player_key: [quotes]}} in deterministic order."""
    g: dict = defaultdict(lambda: defaultdict(list))
    for q in sorted(
        quotes,
        key=lambda q: (
            q.event_id,
            q.market,
            q.player_key,
            q.book,
            q.line,
            q.first_seen_at,
        ),
    ):
        if q.commence_time is not None and q.line is not None:
            g[(q.event_id, q.market)][q.player_key].append(q)
    return g


def _times(players: dict) -> list[datetime]:
    qs = [q for v in players.values() for q in v]
    cut = qs[0].commence_time
    return sorted({x for q in qs for x in (q.first_seen_at, q.last_seen_at) if x < cut})


def _month(d: date) -> str:
    return d.strftime("%Y-%m")


def _modal_line(book_probs) -> float:
    c = Counter(ln for pts in book_probs.values() for ln, _ in pts)
    return min(c, key=lambda ln: (-c[ln], ln))


def _modal_probs(book_probs, line, market):
    got = {}
    for book, pts in book_probs.items():
        ln, p = min(pts, key=lambda t: (abs(t[0] - line), abs(t[1] - 0.5)))
        conv = lines.convert(p, ln, line, market)
        if conv is not None:
            got[book] = conv
    return got


def collect_close_rows(groups, params, key_to_id, box):
    """Per (market, month): weight-fit rows [(probs, y)] and per (market, method) calibration
    [(p, y)] from the closing quotes of every prop (one row per event, player)."""
    rows: dict = defaultdict(list)
    cal: dict = defaultdict(list)
    for (_, market), players in groups.items():
        times = _times(players)
        if not times:
            continue
        close = times[-1]
        for pk, qs in players.items():
            first = qs[0]
            stat, _ = _stat(market, pk, first.game_date, key_to_id, box)
            if stat is None:
                continue
            present = _present(qs, close)
            probs = fp.book_fair(present, close, params.rule)
            if not probs:
                continue
            line = _modal_line(probs)
            if stat == line:
                continue
            y = int(stat > line)
            got = _modal_probs(probs, line, market)
            if len(got) >= 2:
                rows[(market, _month(first.game_date))].append((got, y))
            for m in CAL_METHODS:
                pm = fp.book_fair(present, close, replace(params.rule, method=m))
                g = _modal_probs(pm, line, market) if pm else {}
                if len(g) >= 2:
                    cal[(market, m)].append((consensus.blend(g, None), y))
    return rows, cal


def walk_forward_weights(rows, params) -> dict:
    """{(market, month): {'weights': {...}|None, 'n_rows': int, 'fitted': [...]}}; the weights
    of month m are fitted only on props of earlier months."""
    out: dict = {}
    for market in sorted({m for m, _ in rows}):
        months = sorted({mo for m, mo in rows if m == market})
        for mo in months:
            prior = [
                r for (m, mm), v in rows.items() if m == market and mm < mo for r in v
            ]
            if not prior:
                out[(market, mo)] = {"weights": None, "n_rows": 0, "fitted": []}
                continue
            fit = consensus.fit_weights(prior, min_n=params.min_n_weights)
            out[(market, mo)] = {
                "weights": fit["weights"],
                "n_rows": len(prior),
                "fitted": fit["fitted"],
            }
    return out


def _rng(*parts) -> random.Random:
    return random.Random(":".join(str(p) for p in parts))


def replay_group(event_market, players, weights, params, key_to_id, box):
    """Flag records for one (event, market)."""
    event_id, market = event_market
    times = _times(players)
    if not times:
        return []
    close = times[-1]
    rule = params.rule
    out = []
    for pk, qs in players.items():
        first = qs[0]
        commence = first.commence_time
        stat, void = _stat(market, pk, first.game_date, key_to_id, box)
        close_probs = fp.book_fair(_present(qs, close), close, rule)
        close_pool = _pools(close_probs, weights, market)

        def p_close(line, side):
            if not close_probs:
                return None, 0
            got, s, ws = close_pool(line)
            if not got:
                return None, 0
            p = 1 / (1 + math.exp(-s / ws))
            return (p if side == "o" else 1 - p), len(got)

        def score(price, line, side):
            pc, nc = p_close(line, side)
            return (
                pc,
                nc,
                None if pc is None else pc - odds_math.american_to_prob(price),
                None if pc is None else pc * odds_math.american_to_decimal(price) - 1,
                _win(stat, line, side),
            )

        seen = set()
        for t in times:
            present = _present(qs, t)
            if not present:
                continue
            for f in fast_prop_flags(present, t, market, weights, rule, commence):
                pc, nc, clv, evc, win = score(f.price, f.line, f.side)
                is_close = t == close
                key = (f.book, f.side)
                primary = not is_close and key not in seen
                if not is_close:
                    seen.add(key)
                rec = {
                    "event_id": event_id,
                    "market": market,
                    "player_key": pk,
                    "book": f.book,
                    "side": f.side,
                    "line": f.line,
                    "price": f.price,
                    "fair_prob": f.fair_prob,
                    "ev": f.ev,
                    "playable_to": f.playable_to,
                    "n_books": f.n_books,
                    "t": t,
                    "hours": (commence - t).total_seconds() / 3600,
                    "game_date": first.game_date,
                    "is_close": is_close,
                    "primary": primary,
                    "p_close": pc,
                    "n_close": nc,
                    "clv": None if is_close else clv,
                    "ev_close": evc,
                    "win": win,
                    "void": void,
                    "rand_clv": None,
                    "rand_win": None,
                }
                if primary:
                    cands = sorted(
                        (
                            q.book,
                            q.line,
                            s_,
                            q.over_price if s_ == "o" else q.under_price,
                        )
                        for q in present
                        if q.book not in rule.reference_only
                        and q.book not in rule.consensus_only
                        and fp._fresh(q, t, rule)
                        for s_ in ("o", "u")
                        if (q.over_price if s_ == "o" else q.under_price)
                    )
                    if cands:
                        b, ln, sd, pr = _rng(
                            params.seed, "rand", event_id, market, pk, f.book, f.side
                        ).choice(cands)
                        _, _, rclv, _, rwin = score(pr, ln, sd)
                        rec.update(
                            rand_book=b,
                            rand_side=sd,
                            rand_line=ln,
                            rand_price=pr,
                            rand_clv=rclv,
                            rand_win=rwin,
                        )
                out.append(rec)
    return out


# ----------------------------------------------------------------------------- baselines


def _coin(seed, run, f) -> bool:
    return (
        _rng(seed, "placebo", run, f["event_id"], f["market"], f["player_key"]).random()
        < 0.5
    )


def placebo_summary(primary: list[dict], params: Params) -> dict | None:
    dec = [f for f in primary if f["win"] is not None]
    if not dec:
        return None
    expectation = sum(
        0.5 * odds_math.american_to_decimal(f["price"]) - 1 for f in dec
    ) / len(dec)
    rois, hits, ses = [], [], []
    for run in range(params.placebo_runs):
        views = []
        for f in dec:
            v = _view(f)
            v["win"] = (not f["win"]) if _coin(params.seed, run, f) else f["win"]
            views.append(v)
        r = score_row(views, clv=False)
        rois.append(r["roi"])
        hits.append(r["hit_rate"])
        if r["roi_se"] is not None:
            ses.append(r["roi_se"])
    runs = len(rois)
    return {
        "runs": runs,
        "mean_roi": sum(rois) / runs,
        "mean_hit_rate": sum(hits) / runs,
        "expectation": expectation,
        "se": (
            (sum(ses) / len(ses) / math.sqrt(runs))
            if ses and len(ses) == runs
            else None
        ),
    }


def _verdict_block(primary: list[dict], params: Params) -> dict:
    row = score_row([_view(f) for f in primary])
    rand_views = [_view(f, "rand_") for f in primary if f.get("rand_price") is not None]
    rand_row = score_row(rand_views)
    pairs = [f for f in primary if f["clv"] is not None and f["rand_clv"] is not None]
    paired = clustered_mean(
        [f["clv"] - f["rand_clv"] for f in pairs], [f["game_date"] for f in pairs]
    )
    pl = placebo_summary(primary, params)
    return {
        "verdict": decide(row, pl, rand_row, paired),
        "primary": row,
        "random": rand_row,
        "paired_clv_diff": paired,
        "placebo": pl,
    }


def _calibration(cal) -> list[dict]:
    out = []
    for (market, method), v in sorted(cal.items()):
        eps = 1e-12
        ll = -sum(math.log(min(max(p if y else 1 - p, eps), 1)) for p, y in v) / len(v)
        out.append(
            {
                "market": market,
                "method": method,
                "n": len(v),
                "log_loss": ll,
                "brier": sum((p - y) ** 2 for p, y in v) / len(v),
            }
        )
    return out


# ----------------------------------------------------------------------------- driver


def run_backtest(
    quotes: list[SnapQuote], key_to_id, box, params: Params = Params(), dropped_keys=0
):
    """Full pipeline over plain data. Returns {'flags': [...], 'summary': {...}}."""
    groups = _group(quotes)
    rows, cal = collect_close_rows(groups, params, key_to_id, box)
    wf = walk_forward_weights(rows, params)
    flags: list[dict] = []
    for em, players in groups.items():
        first = next(iter(players.values()))[0]
        w = wf.get((em[1], _month(first.game_date)), {}).get("weights")
        flags.extend(replay_group(em, players, w, params, key_to_id, box))
    flags.sort(
        key=lambda f: (
            f["event_id"],
            f["market"],
            f["player_key"],
            f["book"],
            f["side"],
            f["t"],
        )
    )
    # A void flag (player did not play, or has no box score / name mapping) is not a bet: it
    # is counted below and left out of every scored set, the verdict's n included.
    graded = [f for f in flags if f["void"] is None]
    primary = [f for f in graded if f["primary"]]
    non_close = [f for f in graded if not f["is_close"]]
    closes = [f for f in graded if f["is_close"]]

    def table(key, buckets=None):
        out = {}
        if buckets is None:
            for k in sorted({f[key] for f in primary}):
                out[k] = score_row([_view(f) for f in primary if f[key] == k])
        else:
            for lo, hi in buckets:
                name = f"[{lo},{'inf' if hi == math.inf else hi})"
                sel = [f for f in primary if lo <= f[key] < hi]
                out[name] = score_row([_view(f) for f in sel])
        return out

    block = _verdict_block(primary, params)
    per_market = {
        m: _verdict_block([f for f in primary if f["market"] == m], params)
        for m in sorted({f["market"] for f in primary})
    }
    counts = {
        "dropped_ambiguous_player_keys": dropped_keys,
        "groups": len(groups),
        "props": sum(len(p) for p in groups.values()),
        "flags": len(flags),
        "flags_primary": len(primary),
        "flags_close": len(closes),
        "no_close_clv_primary": sum(f["clv"] is None for f in primary),
        "void_primary": dict(
            Counter(f["void"] for f in flags if f["primary"] and f["void"])
        ),
        "push_primary": sum(1 for f in primary if f["win"] is None and not f["void"]),
    }
    summary = {
        "params": {
            "seed": params.seed,
            "placebo_runs": params.placebo_runs,
            "min_ev": params.rule.min_ev,
            "min_books": params.rule.min_books,
            "method": params.rule.method,
        },
        "counts": counts,
        "verdict": block["verdict"],
        "verdict_rules": VERDICT_RULES,
        "tables": {
            "overall_primary": block["primary"],
            "all_flags": score_row([_view(f) for f in non_close]),
            "is_close_roi_only": score_row([_view(f) for f in closes], clv=False),
            "random_baseline": block["random"],
            "paired_clv_diff": block["paired_clv_diff"],
            "placebo": block["placebo"],
            "by_market": table("market"),
            "by_book": table("book"),
            "by_edge_bucket": table("ev", EDGE_BUCKETS),
            "by_hours_before_tip": table("hours", HOUR_BUCKETS),
        },
        "secondary_verdict_by_market": {m: b["verdict"] for m, b in per_market.items()},
        "weights": {
            f"{m}|{mo}": {
                "weights": v["weights"],
                "n_rows": v["n_rows"],
                "fitted": v["fitted"],
            }
            for (m, mo), v in sorted(wf.items())
        },
        "devig_calibration": _calibration(cal),
    }
    return {"flags": flags, "summary": summary}


# ----------------------------------------------------------------------------- output


def _round(x):
    if isinstance(x, float):
        return round(x, 6) if math.isfinite(x) else None
    if isinstance(x, dict):
        return {str(k): _round(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_round(v) for v in x]
    return x


def summary_json(summary: dict) -> str:
    return json.dumps(_round(summary), sort_keys=True, indent=1) + "\n"


CSV_COLS = (
    "event_id market player_key book side line price fair_prob ev playable_to n_books t hours "
    "game_date is_close primary p_close n_close clv ev_close win void rand_book rand_side "
    "rand_line rand_price rand_clv rand_win"
).split()


def flags_csv(flags: Iterable[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLS)
    for f in flags:
        w.writerow(
            [
                (
                    ""
                    if f.get(c) is None
                    else (_round(f[c]) if isinstance(f[c], float) else f[c])
                )
                for c in CSV_COLS
            ]
        )
    return buf.getvalue()


def _cell(v):
    if v is None:
        return "-"
    return f"{v:.4f}" if isinstance(v, float) else str(v)


def _md(rows: dict, cols) -> str:
    out = ["| group | " + " | ".join(cols) + " |", "|---" * (len(cols) + 1) + "|"]
    for k, r in rows.items():
        out.append(
            f"| {k} | " + " | ".join(_cell(_round(r.get(c))) for c in cols) + " |"
        )
    return "\n".join(out)


def report_md(summary: dict) -> str:
    t = summary["tables"]
    cols = [
        "n",
        "n_dates",
        "clv_mean",
        "clv_lo",
        "clv_hi",
        "clv_pos_share",
        "hits",
        "decided",
        "hit_lo",
        "hit_hi",
        "roi",
        "roi_lo",
        "roi_hi",
        "ev_mean",
        "price_median",
    ]
    parts = [
        f"# Fair-price backtest\n\n**Verdict: {summary['verdict']}**\n",
        f"Params: `{json.dumps(summary['params'], sort_keys=True)}`\n",
        f"Counts: `{json.dumps(summary['counts'], sort_keys=True)}`\n",
        "## Overall\n"
        + _md(
            {
                "primary": t["overall_primary"],
                "all flags": t["all_flags"],
                "is_close (ROI only)": t["is_close_roi_only"],
                "random baseline": t["random_baseline"],
            },
            cols,
        ),
        f"\nPaired CLV diff: `{json.dumps(_round(t['paired_clv_diff']), sort_keys=True)}`\n",
        f"Placebo: `{json.dumps(_round(t['placebo']), sort_keys=True)}`\n",
        "## By market\n" + _md(t["by_market"], cols),
        "\n## By book\n" + _md(t["by_book"], cols),
        "\n## By edge bucket\n" + _md(t["by_edge_bucket"], cols),
        "\n## By hours before tip\n" + _md(t["by_hours_before_tip"], cols),
        "\n## Secondary verdict by market\n"
        + "\n".join(
            f"- {m}: {v}" for m, v in summary["secondary_verdict_by_market"].items()
        ),
        "\n## De-vig calibration at close\n"
        + _md(
            {f"{r['market']} / {r['method']}": r for r in summary["devig_calibration"]},
            ["n", "log_loss", "brier"],
        ),
        "\n## Walk-forward weights\n"
        + "\n".join(
            f"- {k}: n_rows={v['n_rows']} "
            + (
                json.dumps(
                    _round({b: v["weights"][b] for b in v["fitted"]}), sort_keys=True
                )
                if v["weights"]
                else "equal"
            )
            for k, v in summary["weights"].items()
        ),
        "\n## Verdict rules\n"
        + "\n".join(f"- **{k}**: {v}" for k, v in summary["verdict_rules"].items()),
    ]
    return "\n".join(parts) + "\n"
