"""Read-only backtest of NBA totals projections against final scores.

Replays a season point-in-time with the production baseline
(``totals_baseline``) and reports bias and error against the actual total and,
where a market total was stored, against the line. Scores the self-correction
(shrunk mean of the last N errors) and the call policy, then compares how much
of last season the baseline should keep (``BLENDS``).

    PYTHONPATH=. python3 scripts/nba_totals_backtest.py [--season 2025]
"""

from __future__ import annotations

import argparse
import statistics as st
from datetime import date, timedelta
from collections import defaultdict

from app.core.database import SessionLocal
from app.models.predictions_models import NBAGameLines, NBASpreadActuals
from app.services.etl.nba._season import regular_season_start, season_start_year
from app.services.etl.nba.totals_baseline import (
    BIAS_SHRINK,
    BIAS_WINDOW,
    CURRENT_SEASON,
    LAST_SEASON_WEIGHTED,
    MIN_EDGE,
    Blend,
    Final,
    baseline_scores,
)

BLENDS = {
    "last season weighted (old)": LAST_SEASON_WEIGHTED,
    "this season after 5 games": Blend(0, 20, 5),
    "this season after 8 games": Blend(0, 20, 8),
    "this season after 12 games": Blend(0, 20, 12),
    "blend, last season = 5 games": Blend(0, 5, None),
}
EARLY_DAYS = 42


def mae(xs):
    return sum(abs(x) for x in xs) / len(xs) if xs else float("nan")


def total(g):
    return g.home_score + g.away_score


def replay(finals, season, blend=CURRENT_SEASON):
    """[(game, baseline total)] for a season's games, each point-in-time."""
    opener = regular_season_start(season)
    games_in = sorted(
        (
            g
            for g in finals
            if g.game_date >= opener and season_start_year(g.game_date) == season
        ),
        key=lambda g: g.game_date,
    )
    run = []
    for g in games_in:
        s = baseline_scores(
            finals, g.home_team_name, g.away_team_name, g.game_date, blend
        )
        if s is not None:
            run.append((g, sum(s)))
    return run


def compare_blends(finals, lines, season):
    """One line per blend: corrected error overall and early, and its calls."""
    early_end = regular_season_start(season) + timedelta(days=EARLY_DAYS)
    print(
        f"\nblends (corrected window={BIAS_WINDOW} shrink={BIAS_SHRINK}; "
        f"early = first {EARLY_DAYS} days)"
    )
    print(
        f"  {'blend':30s} {'games':>5s} {'bias':>6s} {'MAE':>6s} {'early MAE':>9s}"
        f" {'picks':>5s} {'hit':>6s} {'unders':>6s}"
    )
    for name, blend in BLENDS.items():
        c = corrected(replay(finals, season, blend), BIAS_WINDOW, BIAS_SHRINK)
        if not c:
            continue
        e = [total(g) - q for g, _, q in c]
        early = [total(g) - q for g, _, q in c if g.game_date < early_end]
        picks = [
            (q, total(g), m)
            for g, _, q in c
            if (m := lines.get((g.game_date, g.home_team_name, g.away_team_name)))
            and abs(q - m) >= MIN_EDGE
            and total(g) != m
        ]
        hit = sum((q < m) == (t < m) for q, t, m in picks)
        unders = sum(q < m for q, _, m in picks)
        rate = f"{hit / len(picks):6.1%}" if picks else f"{'n/a':>6s}"
        share = f"{unders / len(picks):6.0%}" if picks else f"{'n/a':>6s}"
        print(
            f"  {name:30s} {len(c):5d} {st.mean(e):+6.2f} {mae(e):6.2f}"
            f" {mae(early):9.2f} {len(picks):5d} {rate} {share}"
        )


def corrected(run, window, shrink):
    """[(game, baseline, corrected)] with the correction learned only from earlier games."""
    out = []
    for i, (g, p) in enumerate(run):
        prev = [x.home_score + x.away_score - q for x, q in run[max(0, i - window) : i]]
        bias = sum(prev) / (len(prev) + shrink) if prev else 0.0
        out.append((g, p, p + bias))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, action="append")
    args = ap.parse_args()
    seasons = args.season or [
        season_start_year(date.today()) - 1,
        season_start_year(date.today()),
    ]
    db = SessionLocal()
    try:
        finals = [
            Final(
                a.game_date,
                a.home_team_name,
                a.away_team_name,
                a.home_score,
                a.away_score,
            )
            for a in db.query(NBASpreadActuals).all()
        ]
        lines = {
            (ln.game_date, ln.home_team_name, ln.away_team_name): float(ln.total)
            for ln in db.query(NBAGameLines).all()
            if ln.total
        }
    finally:
        db.close()

    for season in seasons:
        print(f"\n######## season {season}")
        run = replay(finals, season)
        print(
            f"actuals {len(finals)}; stored market totals {len(lines)}; season {season}: {len(run)} games"
        )
        e0 = [total(g) - p for g, p in run]
        print(f"baseline: bias {st.mean(e0):+.2f}  MAE {mae(e0):.2f}")
        by = defaultdict(list)
        for g, p in run:
            by[(g.game_date.year, g.game_date.month)].append(total(g) - p)
        print(
            "  bias by month:",
            {f"{y}-{m:02d}": round(st.mean(v), 1) for (y, m), v in sorted(by.items())},
        )

        for window, shrink in (
            (30, 10),
            (30, 20),
            (60, 10),
            (BIAS_WINDOW, BIAS_SHRINK),
        ):
            c = corrected(run, window, shrink)
            e = [total(g) - q for g, _, q in c]
            by = defaultdict(list)
            for g, _, q in c:
                by[(g.game_date.year, g.game_date.month)].append(total(g) - q)
            print(
                f"corrected window={window} shrink={shrink}: bias {st.mean(e):+.2f} MAE {mae(e):.2f}"
            )
            print(
                "  bias by month:",
                {
                    f"{y}-{m:02d}": round(st.mean(v), 1)
                    for (y, m), v in sorted(by.items())
                },
            )

        c = corrected(run, BIAS_WINDOW, BIAS_SHRINK)
        have = [
            (g, p, q, lines[(g.game_date, g.home_team_name, g.away_team_name)])
            for g, p, q in c
            if (g.game_date, g.home_team_name, g.away_team_name) in lines
        ]
        print(f"\ngames with a stored market total: {len(have)}")
        if len(have) >= 20:
            report_vs_market(have)
        compare_blends(finals, lines, season)


def report_vs_market(have):
    """have: [(game, baseline, corrected, market total)]."""
    print(
        f"market: bias {st.mean(total(g) - m for g, _, _, m in have):+.2f} MAE {mae([total(g) - m for g, _, _, m in have]):.2f}"
    )
    print(
        f"baseline: MAE {mae([total(g) - p for g, p, _, _ in have]):.2f}; corrected: MAE {mae([total(g) - q for g, _, q, _ in have]):.2f}"
    )
    for w in (0.0, 0.25, 0.5):
        e = [total(g) - (w * q + (1 - w) * m) for g, _, q, m in have]
        print(
            f"  blend w_model={w:.2f} (corrected): bias {st.mean(e):+.2f} MAE {mae(e):.2f}"
        )
    for label, idx in (("baseline", 1), ("corrected", 2)):
        for lo in (0, 2, MIN_EDGE, 6, 8):
            picks = [
                t for t in have if abs(t[idx] - t[3]) >= lo and total(t[0]) != t[3]
            ]
            if len(picks) >= 10:
                hit = sum((t[idx] < t[3]) == (total(t[0]) < t[3]) for t in picks)
                unders = sum(t[idx] < t[3] for t in picks)
                print(
                    f"  {label} |edge|>={lo}: {len(picks)} picks, hit {hit/len(picks):.1%}, {unders/len(picks):.0%} unders"
                )


if __name__ == "__main__":
    main()
