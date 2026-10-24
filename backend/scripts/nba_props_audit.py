"""Read-only audit of stored NBA player-prop projections against actual results.

Joins each stat's projections to its actuals on (date, player) and reports, per
stat: error and bias vs the actual, the sportsbook line's own error, and how
over/under picks against the stored line performed by edge size and level.

    PYTHONPATH=. python3 scripts/nba_props_audit.py [--days 120]
"""

from __future__ import annotations

import argparse
import statistics as st
from collections import defaultdict
from datetime import date, timedelta

from app.core.database import SessionLocal
from app.services.etl.nba.calculate_prediction_accuracy import STAT_CONFIGS

AUDIT_STATS = ("points", "rebounds", "assists")
EDGES = (0.0, 0.5, 1.0, 2.0, 3.0)
BREAKEVEN = 0.5238


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
            seen[key] = (
                float(getattr(r, pf)),
                getattr(r, "fanduel_line", None),
                float(actuals[key]),
                r.date,
            )
    return list(seen.values())


def report(stat, data):
    print(f"\n== {stat}: {len(data)} graded player-games")
    if len(data) < 30:
        return
    err = [a - p for p, _, a, _ in data]
    print(
        f"projection: bias (actual-proj) {st.mean(err):+.2f}  MAE {st.mean(abs(e) for e in err):.2f}"
    )
    lined = [(p, float(l), a, d) for p, l, a, d in data if l]
    print(f"with a stored line: {len(lined)}")
    if len(lined) >= 30:
        le = [a - l for _, l, a, _ in lined]
        pe = [a - p for p, _, a, _ in lined]
        print(
            f"  line: bias {st.mean(le):+.2f} MAE {st.mean(abs(e) for e in le):.2f}; projection on same rows: bias {st.mean(pe):+.2f} MAE {st.mean(abs(e) for e in pe):.2f}"
        )
        rows = [(p, l, a) for p, l, a, _ in lined]
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
        for p, l, a, _ in lined:
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
    for p, _, a, d in data:
        by_month[(d.year, d.month)].append(a - p)
    print(
        "  bias by month:",
        {
            f"{y}-{m:02d}": round(st.mean(v), 2)
            for (y, m), v in sorted(by_month.items())
        },
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=400)
    args = ap.parse_args()
    since = date.today() - timedelta(days=args.days)
    db = SessionLocal()
    try:
        for stat in AUDIT_STATS:
            report(stat, load(db, stat, since))
    finally:
        db.close()


if __name__ == "__main__":
    main()
