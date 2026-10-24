"""Read-only backtest of NBA totals projections against final scores.

Replays each game of a season point-in-time the way production projects it
(last season's scoring, this season blended in after the delay; see
``totals_projector``) and reports bias and error against the actual total and,
where we stored a market line, against the market. Also scores candidate fixes:
a rolling bias correction learned from earlier games and a blend with the line.

    PYTHONPATH=. python3 scripts/nba_totals_backtest.py [--season 2025]
"""

from __future__ import annotations

import argparse
import statistics as st
from bisect import bisect_left
from collections import defaultdict
from datetime import date, timedelta

from app.core.database import SessionLocal
from app.models.predictions_models import NBAGameLines, NBASpreadActuals
from app.services.etl.nba._season import regular_season_start, season_start_year
from app.services.etl.nba.totals_projector import (
    CURRENT_SEASON_DELAY_DAYS,
    CURRENT_SEASON_PRIOR_GAMES,
    MIN_FORM_GAMES,
)

BIAS_WINDOWS = (30, 60, 120)
BLEND_WEIGHTS = (0.0, 0.25, 0.5, 0.75, 1.0)
EDGE_BUCKETS = (0, 2, 4, 6, 8)


class Game:
    __slots__ = ("d", "home", "away", "hs", "as_", "total")

    def __init__(self, a):
        self.d, self.home, self.away = a.game_date, a.home_team_name, a.away_team_name
        self.hs, self.as_ = a.home_score, a.away_score
        self.total = a.home_score + a.away_score


def team_rates(games, team):
    """(scored, allowed, n) per game for a team over games."""
    s = al = n = 0
    for g in games:
        if g.home == team:
            s, al, n = s + g.hs, al + g.as_, n + 1
        elif g.away == team:
            s, al, n = s + g.as_, al + g.hs, n + 1
    return (s / n, al / n, n) if n else (0.0, 0.0, 0)


def blend(prior, cur):
    p_for, p_against, p_n = prior
    c_for, c_against, c_n = cur
    if p_n < MIN_FORM_GAMES:
        return (c_for, c_against) if c_n >= MIN_FORM_GAMES else None
    w = c_n / (c_n + CURRENT_SEASON_PRIOR_GAMES)
    return (1 - w) * p_for + w * c_for, (1 - w) * p_against + w * c_against


def replay(games, year, delay_days):
    """Chronological (game, projection) pairs for season ``year``."""
    opener = regular_season_start(year)
    prior_games = [g for g in games if date(year - 1, 7, 1) <= g.d < opener]
    season = [g for g in games if g.d >= opener and season_start_year(g.d) == year]
    teams = {t for g in season for t in (g.home, g.away)}
    prior = {t: team_rates(prior_games, t) for t in teams}
    out = []
    for g in sorted(season, key=lambda x: x.d):
        use_cur = g.d >= opener + timedelta(days=delay_days)
        before = [x for x in season if x.d < g.d] if use_cur else []
        rates = {}
        for t in (g.home, g.away):
            rates[t] = blend(prior[t], team_rates(before, t) if use_cur else (0, 0, 0))
        if rates[g.home] is None or rates[g.away] is None:
            continue
        home = (rates[g.home][0] + rates[g.away][1]) / 2
        away = (rates[g.away][0] + rates[g.home][1]) / 2
        out.append((g, home + away))
    return out


def mae(xs):
    return sum(abs(x) for x in xs) / len(xs) if xs else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2025)
    args = ap.parse_args()
    db = SessionLocal()
    try:
        games = [Game(a) for a in db.query(NBASpreadActuals).all()]
        lines = {}
        for ln in db.query(NBAGameLines).all():
            if ln.total:
                lines[(ln.game_date, ln.home_team_name, ln.away_team_name)] = float(
                    ln.total
                )
    finally:
        db.close()

    print(f"actuals: {len(games)} games; stored market totals: {len(lines)}")
    for delay in (CURRENT_SEASON_DELAY_DAYS, 0):
        run = replay(games, args.season, delay)
        errs = [g.total - p for g, p in run]  # actual - projected
        print(
            f"\n== season {args.season}, current-season delay {delay}d: {len(run)} games"
        )
        print(f"bias (actual - projected): {st.mean(errs):+.2f}  MAE {mae(errs):.2f}")
        league = st.mean(g.total for g, _ in run)
        print(
            f"mean actual total {league:.1f}; mean projected {st.mean(p for _, p in run):.1f}"
        )
        by_month = defaultdict(list)
        for g, p in run:
            by_month[(g.d.year, g.d.month)].append(g.total - p)
        print(
            "bias by month:",
            {
                f"{y}-{m:02d}": round(st.mean(v), 1)
                for (y, m), v in sorted(by_month.items())
            },
        )

        # rolling bias correction learned only from earlier games
        for w in BIAS_WINDOWS:
            adj = []
            for i, (g, p) in enumerate(run):
                prev = [x.total - q for x, q in run[max(0, i - w) : i]]
                corr = (sum(prev) / (len(prev) + 20)) * 1.0 if prev else 0.0  # shrunk
                adj.append(g.total - (p + corr))
            print(
                f"rolling-bias correction window {w}: bias {st.mean(adj):+.2f} MAE {mae(adj):.2f}"
            )

        have = [
            (g, p, lines[(g.d, g.home, g.away)])
            for g, p in run
            if (g.d, g.home, g.away) in lines
        ]
        print(f"games with a stored market total: {len(have)}")
        if len(have) >= 20:
            print(
                f"market: bias {st.mean(g.total - m for g, _, m in have):+.2f} MAE {mae([g.total - m for g, _, m in have]):.2f}"
                f"; baseline on same games: bias {st.mean(g.total - p for g, p, _ in have):+.2f} MAE {mae([g.total - p for g, p, _ in have]):.2f}"
            )
            for w in BLEND_WEIGHTS:
                e = [g.total - (w * p + (1 - w) * m) for g, p, m in have]
                print(
                    f"  blend w_model={w:.2f}: bias {st.mean(e):+.2f} MAE {mae(e):.2f}"
                )
            for lo in EDGE_BUCKETS:
                picks = [
                    (g, p, m) for g, p, m in have if abs(p - m) >= lo and g.total != m
                ]
                if len(picks) >= 10:
                    hit = sum((p < m) == (g.total < m) for g, p, m in picks)
                    unders = sum(p < m for _, p, m in picks)
                    print(
                        f"  |edge|>={lo}: {len(picks)} picks, hit {hit/len(picks):.1%}, {unders/len(picks):.0%} unders"
                    )


if __name__ == "__main__":
    main()
