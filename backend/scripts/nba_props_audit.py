"""Read-only audit of stored NBA player-prop projections against actual results.

Joins each stat's projections to its actuals on (date, player) and reports, per
stat: error and bias vs the actual, the sportsbook line's own error, how
over/under picks against the stored line performed by edge size and level, and
which teams this season's projections run hottest or coldest on.

    PYTHONPATH=. python3 scripts/nba_props_audit.py [--days 120] [--teams 5]
"""

from __future__ import annotations

import argparse
import statistics as st
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import NamedTuple, Optional

from app.core.database import SessionLocal
from app.models.predictions_models import TeamRoster
from app.services.etl.nba._espn import NBA_TEAM_NAMES
from app.services.etl.nba._season import season_opener
from app.services.etl.nba.calculate_prediction_accuracy import STAT_CONFIGS

AUDIT_STATS = ("points", "rebounds", "assists")
EDGES = (0.0, 0.5, 1.0, 2.0, 3.0)
BREAKEVEN = 0.5238
MIN_TEAM_ROWS = 20


class Graded(NamedTuple):
    proj: float
    line: Optional[float]
    actual: float
    date: date
    player_id: int
    row_id: int


def pick_stats(rows, min_edge):
    """(picks, hits, unders) for over/under picks at |proj - line| >= min_edge.

    rows: (proj, line, actual) with a line. Pushes are skipped."""
    picks = hits = unders = 0
    for proj, line, actual in rows:
        if abs(proj - line) < min_edge or actual == line or proj == line:
            continue
        picks += 1
        hits += (proj > line) == (actual > line)
        unders += proj < line
    return picks, hits, unders


def load(db, stat, since):
    cfg = STAT_CONFIGS[stat]
    pm, am = cfg["projection_model"], cfg["actual_model"]
    pf, af = cfg["projection_field"], cfg["actual_field"]
    actuals = {
        (r.date, r.player_id): getattr(r, af)
        for r in db.query(am).filter(am.date >= since).all()
        if getattr(r, af) is not None
    }
    seen = {}
    for r in db.query(pm).filter(pm.date >= since).order_by(pm.id).all():
        key = (r.date, r.player_id)
        if key in actuals and getattr(r, pf) is not None:
            line = getattr(r, "fanduel_line", None)
            seen[key] = Graded(
                float(getattr(r, pf)),
                float(line) if line else None,
                float(actuals[key]),
                r.date,
                r.player_id,
                r.id,
            )
    return list(seen.values())


def report(stat, data):
    print(f"\n== {stat}: {len(data)} graded player-games")
    if len(data) < 30:
        return
    err = [r.actual - r.proj for r in data]
    print(
        f"projection: bias (actual-proj) {st.mean(err):+.2f}  MAE {st.mean(abs(e) for e in err):.2f}"
    )
    lined = [r for r in data if r.line]
    print(f"with a stored line: {len(lined)}")
    if len(lined) >= 30:
        le = [r.actual - r.line for r in lined]
        pe = [r.actual - r.proj for r in lined]
        print(
            f"  line: bias {st.mean(le):+.2f} MAE {st.mean(abs(e) for e in le):.2f}; projection on same rows: bias {st.mean(pe):+.2f} MAE {st.mean(abs(e) for e in pe):.2f}"
        )
        rows = [(r.proj, r.line, r.actual) for r in lined]
        for lo in EDGES:
            n, h, u = pick_stats(rows, lo)
            if n >= 20:
                print(
                    f"  |edge|>={lo}: {n} picks, hit {h/n:.1%} (breakeven {BREAKEVEN:.1%}), {u/n:.0%} unders"
                )
        # calibration by projected level
        buckets = defaultdict(list)
        cuts = {"points": (10, 18, 25), "rebounds": (4, 7, 10), "assists": (3, 5, 8)}[
            stat
        ]
        for p, l, a in rows:
            k = sum(p >= c for c in cuts)
            buckets[k].append((p, l, a))
        labels = [
            f"<{cuts[0]}",
            f"{cuts[0]}-{cuts[1]}",
            f"{cuts[1]}-{cuts[2]}",
            f">={cuts[2]}",
        ]
        for k in sorted(buckets):
            b = buckets[k]
            n, h, u = pick_stats(b, 1.0)
            hit = f"{h/n:.1%} on {n}" if n >= 10 else "n/a"
            print(
                f"  level {labels[k]}: {len(b)} rows, proj bias {st.mean(a - p for p, _, a in b):+.2f}, line bias {st.mean(a - l for _, l, a in b):+.2f}, hit@1.0 {hit}"
            )
    by_month = defaultdict(list)
    for r in data:
        by_month[(r.date.year, r.date.month)].append(r.actual - r.proj)
    print(
        "  bias by month:",
        {
            f"{y}-{m:02d}": round(st.mean(v), 2)
            for (y, m), v in sorted(by_month.items())
        },
    )


def team_report(data, team_of, top):
    """This season's projection bias per team, most over-projected first.

    Shows the `top` teams at each end (all of them when top covers the league)."""
    opener = season_opener(date.today())
    by_team = defaultdict(list)
    for r in data:
        if r.date >= opener and r.player_id in team_of:
            by_team[team_of[r.player_id]].append(r)
    rows = []
    for team, graded in by_team.items():
        if len(graded) < MIN_TEAM_ROWS:
            continue
        lined = [r for r in graded if r.line]
        lean = st.mean(r.proj - r.line for r in lined) if lined else 0.0
        overs = sum(r.proj > r.line for r in lined) / len(lined) if lined else 0.0
        n, h, _ = pick_stats([(r.proj, r.line, r.actual) for r in lined], 1.0)
        bias = st.mean(r.actual - r.proj for r in graded)
        rows.append((bias, team, len(graded), len(lined), lean, overs, n, h))
    if not rows:
        return
    rows.sort()
    shown = rows if 2 * top >= len(rows) else rows[:top] + rows[-top:]
    print(
        f"  this season by team (bias = actual - proj; lean = proj - line on {sum(r[3] for r in rows)} lined rows):"
    )
    for bias, team, n_rows, n_lined, lean, overs, n, h in shown:
        hit = f"{h / n:.0%} of {n}" if n >= 10 else "n/a"
        print(
            f"    {team:24s} {n_rows:4d} rows  bias {bias:+5.2f}  lean {lean:+5.2f} ({overs:.0%} overs of {n_lined})  hit@1.0 {hit}"
        )


def exposure_report(data, team_of, slots=50):
    """Which teams filled the newest-`slots` rows per date (the old API page)."""
    opener = season_opener(date.today())
    by_date = defaultdict(list)
    for r in data:
        if r.date >= opener:
            by_date[r.date].append(r)
    shown, total = Counter(), Counter()
    for rows in by_date.values():
        rows.sort(key=lambda r: r.row_id, reverse=True)
        shown.update(team_of.get(r.player_id, "?") for r in rows[:slots])
        total.update(team_of.get(r.player_id, "?") for r in rows)
    n_shown, n_total = sum(shown.values()), sum(total.values())
    print(f"  newest-{slots} rows per date over {len(by_date)} dates:")
    for team, n in shown.most_common(8):
        print(
            f"    {team:24s} {n / n_shown:5.1%} of shown rows vs {total[team] / n_total:5.1%} of all rows"
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=400)
    ap.add_argument(
        "--teams", type=int, default=5, help="teams to show at each end of the bias"
    )
    ap.add_argument("--exposure", action="store_true")
    args = ap.parse_args()
    since = date.today() - timedelta(days=args.days)
    db = SessionLocal()
    try:
        team_of = {
            r.player_id: NBA_TEAM_NAMES.get(r.team_id, str(r.team_id))
            for r in db.query(TeamRoster).all()
        }
        for stat in AUDIT_STATS:
            data = load(db, stat, since)
            report(stat, data)
            team_report(data, team_of, args.teams)
            if args.exposure:
                exposure_report(data, team_of)
    finally:
        db.close()


if __name__ == "__main__":
    main()
