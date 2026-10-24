"""Read-only backtest of NBA totals projections against final scores.

Replays a season point-in-time with the production baseline
(``totals_baseline``) and reports bias and error against the actual total and,
where a market total was stored, against the line. Scores the self-correction
(shrunk mean of the last N errors) and the call policy.

    PYTHONPATH=. python3 scripts/nba_totals_backtest.py [--season 2025]
"""

from __future__ import annotations

import argparse
import statistics as st
from datetime import date
from collections import defaultdict

from app.core.database import SessionLocal
from app.models.predictions_models import NBAGameLines, NBASpreadActuals
from app.services.etl.nba._season import regular_season_start, season_start_year
from app.services.etl.nba.totals_baseline import (
    BIAS_SHRINK,
    BIAS_WINDOW,
    MIN_EDGE,
    Final,
    baseline_scores,
)


def mae(xs):
    return sum(abs(x) for x in xs) / len(xs) if xs else float("nan")


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
        opener = regular_season_start(season)
        season = sorted(
            (
                g
                for g in finals
                if g.game_date >= opener and season_start_year(g.game_date) == season
            ),
            key=lambda g: g.game_date,
        )
        run = []
        for g in season:
            s = baseline_scores(finals, g.home_team_name, g.away_team_name, g.game_date)
            if s is not None:
                run.append((g, sum(s)))
        total = lambda g: g.home_score + g.away_score  # noqa: E731
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
        if len(have) < 20:
            continue
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
