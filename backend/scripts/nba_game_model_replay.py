"""Read-only replay of the NBA game projections (total, margin, win probability).

For every game of the season it recomputes, strictly from information available
before that game's date, what each candidate formula would have published, and
scores it against the final score and the line. Used to pick the published
formula (NBA-2/3/6/7/8) and to re-check it; run it against a copy of production.

Inputs: pred_nba_spread_actuals (finals), pred_nba_game_lines, and the stored
projection rows (frozen at game start: their market line, their injury / form
adjustments and the raw model margin are what was known before tip).

    PYTHONPATH=. python3 scripts/nba_game_model_replay.py [--season 2026] [--until 2026-11-14]
"""

from __future__ import annotations

import argparse
import math
import statistics as st
from collections import defaultdict
from datetime import date, timedelta

from app.core.database import SessionLocal
from app.models.predictions_models import (
    NBAGameLines,
    NBASpreadActuals,
    NBASpreadProjections,
    NBATotalsProjections,
)
from app.services.etl.nba._season import regular_season_start
from app.services.etl.nba.market_anchor import anchored, fit_anchor
from app.services.etl.nba.totals_baseline import (
    BREAKEVEN,
    MIN_EDGE,
    MIN_PICKS_FOR_RECORD,
    Final,
    baseline_scores,
    recent_bias,
)

SPREAD_MIN_EDGE = 2.0


def wilson(h, n, z=1.96):
    if not n:
        return float("nan"), float("nan")
    p = h / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    w = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - w, c + w


def hit_str(h, n):
    if not n:
        return "     n=0            "
    lo, hi = wilson(h, n)
    return f"{100 * h / n:5.1f}% n={n:3d} [{100 * lo:4.1f},{100 * hi:4.1f}]"


def mae(xs):
    return sum(abs(x) for x in xs) / len(xs) if xs else float("nan")


def key(r):
    return (r.game_date, r.home_team_name, r.away_team_name)


# ---------------------------------------------------------------- loading


def load(db):
    finals = sorted(
        (
            Final(
                a.game_date,
                a.home_team_name,
                a.away_team_name,
                a.home_score,
                a.away_score,
            )
            for a in db.query(NBASpreadActuals).all()
        ),
        key=lambda g: g.game_date,
    )
    lines = {key(g): g for g in db.query(NBAGameLines).all()}
    tp = {key(p): p for p in db.query(NBATotalsProjections).all()}
    sp = {key(p): p for p in db.query(NBASpreadProjections).all()}
    return finals, lines, tp, sp


def team_dates(finals, lines):
    """Every date each team played or was scheduled (finals and the line table)."""
    out = defaultdict(set)
    for g in list(finals) + list(lines.values()):
        out[g.home_team_name].add(g.game_date)
        out[g.away_team_name].add(g.game_date)
    return out


def schedule_rest(dates, home, away, d):
    """The projector's rest rule, on schedule dates instead of box-score rows."""
    adj = 0.0
    for team in (home, away):
        prev = [x for x in dates.get(team, ()) if x < d]
        if not prev:
            continue
        days = (d - max(prev)).days
        if days == 1:
            adj -= 2.0
        elif days >= 4:
            adj += 0.5
    return max(-5.0, min(adj, 2.0)), sum(
        1 for t in (home, away) if (d - timedelta(days=1)) in dates.get(t, ())
    )


# ---------------------------------------------------------------- totals


def totals_rows(finals, lines, tp, season, until):
    """Per game: actual, market, stored values and the point-in-time model."""
    opener = regular_season_start(season)
    first = regular_season_start(season - 1)
    rb_cache = {}
    dates = team_dates(finals, lines)
    out = []
    for g in finals:
        if not (first <= g.game_date < until):
            continue
        d = g.game_date
        s = baseline_scores(finals, g.home_team_name, g.away_team_name, d)
        if s is None:
            continue
        if d not in rb_cache:
            rb_cache[d] = recent_bias(finals, d)[0]
        p = tp.get(key(g))
        ln = lines.get(key(g))
        market = (p.market_total if p and p.market_total else None) or (
            ln.total if ln and ln.total else None
        )
        rest, b2b = schedule_rest(dates, g.home_team_name, g.away_team_name, d)
        out.append(
            dict(
                d=d,
                current=d >= opener,
                actual=g.home_score + g.away_score,
                market=market,
                base=sum(s),
                model=sum(s) + rb_cache[d],
                published=p.projected_total if p else None,
                injury=(p.injury_adjustment or 0.0) if p else None,
                form=(p.form_adjustment or 0.0) if p else None,
                rest_stored=(p.rest_adjustment or 0.0) if p else None,
                rest=rest,
                b2b=b2b,
                venue=2.5 if "Nuggets" in g.home_team_name else 0.0,
            )
        )
    return out


def walk_forward(rows, model_key, market_key, actual_key, **fit):
    """Anchored value per row, fitted only on rows from earlier dates."""
    hist = []
    out = []
    i = 0
    by_date = sorted(rows, key=lambda r: r["d"])
    for r in by_date:
        while i < len(by_date) and by_date[i]["d"] < r["d"]:
            h = by_date[i]
            if h[market_key] is not None and h[model_key] is not None:
                hist.append((h[model_key], h[market_key], h[actual_key]))
            i += 1
        a = fit_anchor(hist, **fit)
        out.append((r, a))
    return out


def score(name, rows, proj, market_key, actual_key, thresholds, spread=False):
    """Bias / MAE / gap to market / hit rate by edge threshold."""
    xs = [(r, proj(r)) for r in rows if proj(r) is not None]
    if not xs:
        print(f"  {name:62s} n=0")
        return
    e = [r[actual_key] - p for r, p in xs]
    lined = [(r, p) for r, p in xs if r[market_key] is not None]
    gap = mae([r[actual_key] - p for r, p in lined]) - mae(
        [r[actual_key] - r[market_key] for r, _ in lined]
    )
    parts = []
    for t in thresholds:
        h = n = 0
        for r, p in lined:
            edge = p - r[market_key]
            cover = r[actual_key] - r[market_key]
            if abs(edge) < t or edge == 0 or cover == 0:
                continue
            n += 1
            h += (edge > 0) == (cover > 0)
        parts.append(f"|e|>={t:g}: {hit_str(h, n)}")
    print(
        f"  {name:62s} n={len(xs):4d} bias {st.mean(e):+6.2f} MAE {mae(e):6.2f}"
        f" gap {gap:+5.2f} | " + " | ".join(parts)
    )


def gate_sim(rows, proj, market_key, actual_key, min_edge, label):
    """What a version-scoped record gate would have done, day by day."""
    hits = picks = 0
    shown = shown_hits = days_open = 0
    by_day = defaultdict(list)
    for r in rows:
        if proj(r) is not None and r[market_key] is not None:
            by_day[r["d"]].append(r)
    first_open = None
    for d in sorted(by_day):
        rate = (hits + 10) / (picks + 20)
        open_ = picks >= MIN_PICKS_FOR_RECORD and rate >= BREAKEVEN
        days_open += open_
        if open_ and first_open is None:
            first_open = d
        for r in by_day[d]:
            edge = proj(r) - r[market_key]
            cover = r[actual_key] - r[market_key]
            if abs(edge) < min_edge or cover == 0:
                continue
            ok = (edge > 0) == (cover > 0)
            picks += 1
            hits += ok
            if open_:
                shown += 1
                shown_hits += ok
    print(
        f"  gate [{label}]: would-be calls {hits}/{picks}; days open {days_open}"
        f"/{len(by_day)} (first {first_open}); calls shown {hit_str(shown_hits, shown)}"
    )


TOTALS_GRID = [
    (w, kp, ap)
    for w in (150, 300, 600)
    for kp, ap in (
        (50, None),
        (200, None),
        (400, None),
        (50, 100),
        (200, 100),
        (400, 100),
    )
]
SPREAD_GRID = [
    (w, kp, ap)
    for w in (100, 200, 400)
    for kp, ap in ((50, None), (200, None), (400, None), (50, 100), (200, 100))
]


def label_of(w, kp, ap):
    return f"W={w} k_prior={kp} a_prior={'inf' if ap is None else ap}"


def variants(rows, subsets, grid, th):
    """Score each (window, k_prior, a_prior) on each subset; {label: {id(row): value}}."""
    results = {}
    for w, kp, ap in grid:
        wf = walk_forward(
            rows,
            "model",
            "market",
            "actual",
            window=w,
            k_prior=kp,
            a_prior=ap,
        )
        vals = {id(r): anchored(r["model"], r["market"], a) for r, a in wf}
        fits = {id(r): a for r, a in wf}
        label = label_of(w, kp, ap)
        results[label] = vals
        for name, sub in subsets.items():
            ks = [fits[id(r)].k for r in sub]
            as_ = [fits[id(r)].a for r in sub]
            score(
                f"{label} [{name}] k {min(ks):.2f}-{max(ks):.2f} a {min(as_):+.1f}..{max(as_):+.1f}",
                sub,
                lambda r: vals.get(id(r)),
                "market",
                "actual",
                th,
            )
    return results


def report_totals(finals, lines, tp, season, until):
    rows = totals_rows(finals, lines, tp, season, until)
    cur = [r for r in rows if r["current"]]
    print(f"\n######## TOTALS season {season} (games before {until})")
    print(
        f"games this season {len(cur)}; with market {sum(r['market'] is not None for r in cur)};"
        f" with a stored projection {sum(r['published'] is not None for r in cur)};"
        f" history rows (last season + this) {len(rows)}"
    )
    th = (0, 1, 2, MIN_EDGE)
    pub = [r for r in cur if r["published"] is not None and r["market"] is not None]
    print(f"\n-- games with a stored projection and a line (n={len(pub)})")
    cands = {
        "as published": lambda r: r["published"],
        "market": lambda r: r["market"],
        "base only": lambda r: r["base"],
        "base + baseline bias (no adjustments)": lambda r: r["model"],
        "  + injury (stored)": lambda r: r["model"] + r["injury"],
        "  + form (stored, x0.3)": lambda r: r["model"] + r["form"],
        "  + rest (from schedule)": lambda r: r["model"] + r["rest"],
        "  + rest (stored, box-score derived)": lambda r: r["model"] + r["rest_stored"],
        "  + venue": lambda r: r["model"] + r["venue"],
    }
    for name, f in cands.items():
        score(name, pub, f, "market", "actual", th)

    prev = [r for r in rows if not r["current"] and r["market"] is not None]
    print(
        f"\n-- market anchored, walk-forward fit on (base + baseline bias); scored on last"
        f" season (n={len(prev)}, used to choose) and this season (test)"
    )
    results = variants(rows, {"last season": prev, "this season": pub}, TOTALS_GRID, th)
    return rows, cur, pub, results


def report_totals_choice(rows, cur, pub, chosen, label):
    print(f"\n-- chosen: {label}")
    allr = [r for r in cur]
    score("chosen, all games this season", allr, chosen, "market", "actual", (0, 2, 4))
    score(
        "market, all games with a line",
        [r for r in allr if r["market"] is not None],
        lambda r: r["market"],
        "market",
        "actual",
        (0,),
    )
    nomkt = [r for r in allr if r["market"] is None]
    if nomkt:
        score(
            "chosen, games with no line (model alone)",
            nomkt,
            chosen,
            "market",
            "actual",
            (),
        )
    # does a schedule rest term earn its place on top of the chosen number?
    xs = [(r["rest"], r["actual"] - chosen(r)) for r in pub if chosen(r) is not None]
    mx = st.mean(x for x, _ in xs)
    my = st.mean(y for _, y in xs)
    sxx = sum((x - mx) ** 2 for x, _ in xs)
    slope = sum((x - mx) * (y - my) for x, y in xs) / sxx if sxx else float("nan")
    print(
        f"  residual (actual - chosen) on schedule rest term: slope {slope:+.2f} (1 = add it, 0 = noise)"
    )
    for b2b in (0, 1, 2):
        sub = [r for r in pub if r["b2b"] == b2b]
        if sub:
            print(
                f"   teams on a true back-to-back = {b2b}: n={len(sub):3d} mean actual - chosen"
                f" {st.mean(r['actual'] - chosen(r) for r in sub):+.2f}"
                f" actual - market {st.mean(r['actual'] - r['market'] for r in sub):+.2f}"
            )
    gate_sim(
        pub, lambda r: r["published"], "market", "actual", MIN_EDGE, "as published"
    )
    gate_sim(
        allr, chosen, "market", "actual", MIN_EDGE, "chosen, new version from opener"
    )
    by = defaultdict(list)
    for r in allr:
        if chosen(r) is not None:
            by[r["d"] - timedelta(days=r["d"].weekday())].append(
                r["actual"] - chosen(r)
            )
    print(
        "  bias by week:", {str(k): round(st.mean(v), 2) for k, v in sorted(by.items())}
    )


# ---------------------------------------------------------------- spread


def spread_rows(finals, lines, sp, until):
    fin = {key(g): g for g in finals}
    out = []
    for k_, p in sp.items():
        g = fin.get(k_)
        if g is None or p.game_date >= until:
            continue
        ln = lines.get(k_)
        spread = (
            p.market_spread_home
            if p.market_spread_home is not None
            else (ln.spread_home if ln else None)
        )
        factors = p.factors if isinstance(p.factors, dict) else {}
        model = factors.get("model_margin", p.projected_margin)
        ml = None
        if ln and ln.moneyline_home is not None and ln.moneyline_away is not None:
            ih, ia = implied(ln.moneyline_home), implied(ln.moneyline_away)
            ml = (ih / (ih + ia), ln.moneyline_home, ln.moneyline_away)
        out.append(
            dict(
                d=p.game_date,
                actual=g.home_score - g.away_score,
                won=1.0 if g.home_score > g.away_score else 0.0,
                market=-spread if spread is not None else None,
                model=model,
                published_p=p.home_win_prob,
                elo=factors.get("elo_pace_margin"),
                method=factors.get("method"),
                ml=ml,
            )
        )
    return sorted(out, key=lambda r: r["d"])


def implied(american):
    return 100 / (american + 100) if american > 0 else -american / (-american + 100)


def logistic(m, s):
    return 1.0 / (1.0 + math.exp(-m / s))


def brier(pairs):
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs) if pairs else float("nan")


def fit_scale(pairs):
    """MLE logistic scale for (margin, won) pairs on a 0.1 grid."""
    best = None
    for i in range(40, 121):
        s = i / 10
        ll = -sum(
            math.log(max(1e-9, logistic(m, s) if y else 1 - logistic(m, s)))
            for m, y in pairs
        )
        if best is None or ll < best[1]:
            best = (s, ll)
    return best[0]


def calibration(name, pairs):
    print(f"   calibration [{name}] (bin: mean p, observed [95% interval], n)")
    edges = (0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0001)
    bad = 0
    for lo, hi in zip(edges, edges[1:]):
        b = [(p, y) for p, y in pairs if lo <= p < hi]
        if not b:
            continue
        mp = st.mean(p for p, _ in b)
        h = sum(y for _, y in b)
        wl, wh = wilson(h, len(b))
        off = not (wl <= mp <= wh)
        bad += off
        print(
            f"     [{lo:.1f},{min(hi, 1):.1f}) p {mp:.3f} obs {h / len(b):.3f}"
            f" [{wl:.3f},{wh:.3f}] n={len(b):3d}{'  OFF' if off else ''}"
        )
    print(f"     bins outside their interval: {bad}")


def report_spread(finals, lines, sp, season, until):
    rows = spread_rows(finals, lines, sp, until)
    opener = regular_season_start(season)
    cur = [r for r in rows if r["d"] >= opener and r["market"] is not None]
    print(f"\n######## SPREAD / WIN PROBABILITY season {season} (games before {until})")
    print(
        f"graded spread rows {len(rows)}; this season with a line {len(cur)};"
        f" methods {dict((m, sum(r['method'] == m for r in cur)) for m in {r['method'] for r in cur})}"
    )
    th = (0, 1, SPREAD_MIN_EDGE)
    score(
        "as published (model margin)", cur, lambda r: r["model"], "market", "actual", th
    )
    score("market", cur, lambda r: r["market"], "market", "actual", (0,))
    score(
        "elo+pace (factors)",
        [r for r in cur if r["elo"] is not None],
        lambda r: r["elo"],
        "market",
        "actual",
        th,
    )
    print("\n-- market anchored, walk-forward fit on the stored model margin")
    results = variants(rows, {"this season": cur}, SPREAD_GRID, th)
    return rows, cur, results


def report_winprob(finals, lines, rows, cur, chosen, season):
    opener = regular_season_start(season)
    # Fit the scale on last season's market margins only (out of sample here).
    fin = {key(g): g for g in finals}
    prior = []
    for k_, ln in lines.items():
        g = fin.get(k_)
        if (
            g
            and ln.spread_home is not None
            and k_[0] < opener
            and g.home_score != g.away_score
        ):
            prior.append((-ln.spread_home, 1.0 if g.home_score > g.away_score else 0.0))
    s_fit = fit_scale(prior)
    s_cur = fit_scale([(r["market"], r["won"]) for r in cur])
    print(
        f"\n-- win probability: logistic scale fitted on last season's market margins"
        f" (n={len(prior)}): {s_fit}; on this season's (in sample, reference only): {s_cur}"
    )
    with_ml = [r for r in cur if r["ml"] is not None]
    cands = {
        "as published (model margin / 7.0)": lambda r: r["published_p"],
        "market margin / 7.0": lambda r: logistic(r["market"], 7.0),
        f"market margin / {s_fit}": lambda r: logistic(r["market"], s_fit),
        f"chosen margin / {s_fit}": lambda r: logistic(chosen(r), s_fit),
        "moneyline, de-vigged": lambda r: r["ml"][0],
    }
    for name, f in cands.items():
        pairs = [(f(r), r["won"]) for r in with_ml]
        print(f"  {name:40s} Brier {brier(pairs):.4f} (n={len(pairs)})")
    calibration("as published", [(r["published_p"], r["won"]) for r in cur])
    calibration(
        f"chosen margin / {s_fit}",
        [(logistic(chosen(r), s_fit), r["won"]) for r in cur],
    )
    # Moneyline candidates the auto-pick source would build (flat 1u at the line price).
    for name, f in (
        ("as published", lambda r: r["published_p"]),
        (f"chosen / {s_fit}", lambda r: logistic(chosen(r), s_fit)),
        (
            f"chosen / {s_fit}, model part only",
            lambda r: r["ml"][0]
            + logistic(chosen(r), s_fit)
            - logistic(r["market"], s_fit),
        ),
    ):
        for t in (0.0, 0.03):
            n = w = 0
            units = 0.0
            for r in with_ml:
                edge = f(r) - r["ml"][0]
                if abs(edge) <= t:
                    continue
                home = edge > 0
                price = r["ml"][1] if home else r["ml"][2]
                won = (r["actual"] > 0) == home
                n += 1
                w += won
                units += (price / 100 if price > 0 else 100 / -price) if won else -1
            print(
                f"  moneyline candidates [{name}] |edge|>{t:.2f}: n={n} won {hit_str(w, n)}"
                f" ROI {units / n if n else float('nan'):+.3f}"
            )
    return s_fit


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--until", type=date.fromisoformat, default=date.today())
    ap.add_argument("--totals-choice", default="W=600 k_prior=200 a_prior=inf")
    ap.add_argument("--spread-choice", default="W=200 k_prior=200 a_prior=inf")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        finals, lines, tp, sp = load(db)
    finally:
        db.close()
    rows, cur, pub, tres = report_totals(finals, lines, tp, args.season, args.until)
    tv = tres[args.totals_choice]
    report_totals_choice(
        rows,
        cur,
        pub,
        lambda r: tv.get(id(r)) if r["market"] is not None else r["model"],
        args.totals_choice,
    )
    srows, scur, sres = report_spread(finals, lines, sp, args.season, args.until)
    sv = sres[args.spread_choice]
    print(f"\n-- spread chosen: {args.spread_choice}")
    gate_sim(
        scur, lambda r: r["model"], "market", "actual", SPREAD_MIN_EDGE, "as published"
    )
    gate_sim(
        scur,
        lambda r: sv.get(id(r)),
        "market",
        "actual",
        SPREAD_MIN_EDGE,
        "chosen, new version",
    )
    report_winprob(finals, lines, srows, scur, lambda r: sv.get(id(r)), args.season)


if __name__ == "__main__":
    main()
