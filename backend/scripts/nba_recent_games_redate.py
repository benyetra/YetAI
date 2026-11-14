#!/usr/bin/env python3
"""Re-date and de-duplicate pred_recent_games against ESPN finals (NBA-1).

Before #173 the NBA ingest filed each box score under the API-Sports UTC date, so an
evening game sits one day late; after #173 a re-run filed the same game under the right
date without removing the late copy (same player, same game on D and D+1). The true date
of each row is taken from pred_nba_spread_actuals (ESPN finals, Eastern-dated): the row's
opponent and home flag pick the game on the stored date or the day before. Rows that
cannot be placed unambiguously are reported and never touched.

Writes (``--apply``, one transaction): delete duplicate copies, move rows one day
earlier. Idempotent: a second run finds nothing to do.

Dry run is the default:
  cd backend
  PYTHONPATH=. python3 scripts/nba_recent_games_redate.py [--season 2025]
Write the corrections:
  PYTHONPATH=. python3 scripts/nba_recent_games_redate.py --apply
"""

from __future__ import annotations

import argparse
import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Iterable

ONE_DAY = timedelta(days=1)


@dataclass
class Plan:
    moves: list[tuple[int, date, date]] = field(default_factory=list)  # id, old, new
    deletes: list[int] = field(default_factory=list)
    unresolved: list[tuple[Any, str]] = field(default_factory=list)
    conflicts: list[tuple[Any, date]] = field(default_factory=list)
    box_mismatch: list[tuple[int, int]] = field(default_factory=list)  # deleted, kept
    skipped_beyond_schedule: int = 0
    # (season, month) -> [rows, to_move, to_delete, unresolved]
    table: dict[tuple[int, int], list[int]] = field(default_factory=dict)


def season_of(d: date) -> int:
    """League start year (Oct-Sep)."""
    return d.year if d.month >= 10 else d.year - 1


def _box(r: Any) -> tuple:
    return (r.minutes, r.points, r.rebounds, r.assists)


def plan_redate(rows: Iterable[Any], games: Iterable[tuple[date, int, int]]) -> Plan:
    """Pure planner. rows: id, player_id, game_date, opponent_team_id, home_game,
    minutes/points/rebounds/assists, optional api_game_id. games: (date, home, away)."""
    games = list(games)
    by_date: dict[date, list[tuple[int, int]]] = defaultdict(list)
    for d, h, a in games:
        by_date[d].append((h, a))
    last = max(by_date) if by_date else date.min
    plan = Plan()
    rows = list(rows)
    considered = [r for r in rows if r.game_date <= last]
    plan.skipped_beyond_schedule = len(rows) - len(considered)

    def cands(r: Any) -> list[tuple[date, int]]:
        """(date, player team) for the game on the stored date and the day before."""
        out = []
        for d in (r.game_date, r.game_date - ONE_DAY):
            for h, a in by_date.get(d, ()):
                if r.home_game is not False and a == r.opponent_team_id:
                    out.append((d, h))
                elif r.home_game is not True and h == r.opponent_team_id:
                    out.append((d, a))
        return out

    true: dict[int, date] = {}  # row id -> true date
    team: dict[int, int] = {}  # row id -> player's team (when known)
    reason: dict[int, str] = {}
    two_same: list[tuple[Any, list[tuple[date, int]]]] = []
    two_diff: list[tuple[Any, list[tuple[date, int]]]] = []
    for r in considered:
        c = cands(r)
        if len(c) == 1:
            true[r.id], team[r.id] = c[0]
        elif not c:
            reason[r.id] = "no_game"
        elif len({t for _, t in c}) == 2:
            two_diff.append((r, c))
        else:
            two_same.append((r, c))

    # Step 4: two candidates, different teams -> use the player's neighbouring teams.
    by_player: dict[int, list[tuple[date, int]]] = defaultdict(list)
    for r in considered:
        if r.id in true:
            by_player[r.player_id].append((true[r.id], team[r.id]))
    for v in by_player.values():
        v.sort()
    resolved4: list[tuple[Any, date, int]] = []
    for r, c in two_diff:
        seq = by_player.get(r.player_id, [])
        dates = [d for d, _ in seq]
        x = r.game_date
        lo = bisect_left(dates, x - ONE_DAY)  # first index with date >= X-1
        hi = bisect_right(dates, x)  # first index with date > X
        nbr = {t for _, t in seq[lo:hi]}
        if lo:
            nbr.add(seq[lo - 1][1])
        if hi < len(seq):
            nbr.add(seq[hi][1])
        pick = [(d, t) for d, t in c if t in nbr]
        if len(pick) == 1:
            resolved4.append((r, *pick[0]))
        else:
            reason[r.id] = "team_unknown"
    for r, d, t in resolved4:
        true[r.id], team[r.id] = d, t

    # Step 5: same two teams on consecutive days.
    occ: dict[tuple[int, date], list[Any]] = defaultdict(list)
    for r in considered:
        if r.id in true:
            occ[(r.player_id, true[r.id])].append(r)
    bucket: dict[tuple, list[Any]] = defaultdict(list)
    for r, _ in two_same:
        bucket[(r.game_date, r.opponent_team_id, r.home_game)].append(r)

    def settle(r: Any, d: date) -> None:
        true[r.id] = d
        occ[(r.player_id, d)].append(r)

    pending = [r for r, _ in two_same]
    changed = True
    while changed and pending:
        changed = False
        for r in list(pending):
            x, p = r.game_date, r.player_id
            near = {
                d: [o for o in occ.get((p, d), ()) if o.id != r.id]
                for d in (x - ONE_DAY, x)
            }
            same = {
                d for d, os_ in near.items() if any(_box(o) == _box(r) for o in os_)
            }
            new = None
            if len(same) == 1:
                new = next(iter(same))
            elif not same:
                prev_o, cur_o = near[x - ONE_DAY], near[x]
                if prev_o and not cur_o:
                    new = x
                elif cur_o and not prev_o:
                    new = x - ONE_DAY
            if new is not None:
                settle(r, new)
                pending.remove(r)
                changed = True
        if not changed:  # bucket pass: copy the date everyone else in the bucket took
            for r in list(pending):
                k = (r.game_date, r.opponent_team_id, r.home_game)
                ds = {true[o.id] for o in bucket[k] if o.id in true}
                if len(ds) == 1:
                    settle(r, next(iter(ds)))
                    pending.remove(r)
                    changed = True
    for r in pending:
        reason[r.id] = "two_game_set"

    # Step 6: duplicates (same player, same true date).
    groups: dict[tuple[int, date], list[Any]] = defaultdict(list)
    for r in considered:
        if r.id in true:
            groups[(r.player_id, true[r.id])].append(r)
    deleted: set[int] = set()
    for g in groups.values():
        if len(g) < 2:
            continue
        keep = max(
            g,
            key=lambda o: (
                getattr(o, "api_game_id", None) is not None,
                o.game_date == true[o.id],
                o.id,
            ),
        )
        for o in g:
            if o is not keep:
                deleted.add(o.id)
                if _box(o) != _box(keep):
                    plan.box_mismatch.append((o.id, keep.id))
    plan.deletes = sorted(deleted)

    # Step 7: moves (a kept row whose true date differs from the stored one).
    moving = {
        r.id
        for r in considered
        if r.id in true and r.id not in deleted and true[r.id] != r.game_date
    }
    staying = {
        (r.player_id, r.game_date)
        for r in rows
        if r.id not in deleted and r.id not in moving
    }
    for r in sorted(
        (r for r in considered if r.id in moving), key=lambda r: (r.game_date, r.id)
    ):
        if (r.player_id, true[r.id]) in staying:
            plan.conflicts.append((r, true[r.id]))
        else:
            plan.moves.append((r.id, r.game_date, true[r.id]))
    for r in considered:
        if r.id not in true:
            plan.unresolved.append((r, reason[r.id]))

    moved = {m[0] for m in plan.moves}
    for r in considered:
        d = true.get(r.id, r.game_date)
        row = plan.table.setdefault((season_of(d), d.month), [0, 0, 0, 0])
        row[0] += 1
        row[1] += r.id in moved
        row[2] += r.id in deleted
        row[3] += r.id not in true
    return plan


def load_games(db: Any) -> list[tuple[date, int, int]]:
    from app.models.predictions_models import NBASpreadActuals
    from app.services.etl.nba._espn import NBA_TEAM_NAMES

    ids = {n: i for i, n in NBA_TEAM_NAMES.items()}
    out = []
    for g in db.query(NBASpreadActuals).all():
        try:
            out.append((g.game_date, ids[g.home_team_name], ids[g.away_team_name]))
        except KeyError as exc:
            raise SystemExit(f"unknown team name in pred_nba_spread_actuals: {exc}")
    return out


def load_rows(db: Any, season: int | None) -> list[Any]:
    """Only the columns the planner needs; api_game_id when the table has it."""
    from sqlalchemy import inspect

    from app.models.predictions_models import RecentGames as R

    have = {c["name"] for c in inspect(db.get_bind()).get_columns(R.__tablename__)}
    cols = [R.id, R.player_id, R.game_date, R.opponent_team_id, R.home_game]
    cols += [R.minutes, R.points, R.rebounds, R.assists]
    if "api_game_id" in have and hasattr(R, "api_game_id"):
        cols.append(R.api_game_id)
    q = db.query(*cols)
    if season:
        q = q.filter(
            R.game_date >= date(season, 10, 1), R.game_date < date(season + 1, 10, 1)
        )
    return q.all()


def apply_plan(db: Any, plan: Plan) -> None:
    """Delete duplicates, then move rows ascending by stored date (unique key is not
    deferrable; every move is one day earlier so each target is freed first)."""
    from sqlalchemy import bindparam, delete, text, update

    from app.models.predictions_models import RecentGames

    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
    for i in range(0, len(plan.deletes), 500):
        db.execute(
            delete(RecentGames).where(RecentGames.id.in_(plan.deletes[i : i + 500]))
        )
    stmt = (
        update(RecentGames)
        .where(RecentGames.id == bindparam("b_id"))
        .values(game_date=bindparam("b_date"))
    )
    for _id, _old, new in sorted(plan.moves, key=lambda m: (m[1], m[0])):
        db.execute(stmt, {"b_id": _id, "b_date": new})


def report(plan: Plan, applied: bool) -> None:
    print("season month   rows   move   dup  unresolved")
    tot = [0, 0, 0, 0]
    for (s, m), v in sorted(plan.table.items()):
        print(f"{s}   {m:>5} {v[0]:>6} {v[1]:>6} {v[2]:>5} {v[3]:>10}")
        tot = [a + b for a, b in zip(tot, v)]
    print(
        f"TOTAL rows={tot[0]} moves={len(plan.moves)} duplicates={len(plan.deletes)} "
        f"unresolved={len(plan.unresolved)} conflicts={len(plan.conflicts)} "
        f"skipped_beyond_schedule={plan.skipped_beyond_schedule} "
        f"duplicate_box_differs={len(plan.box_mismatch)}"
    )
    for r, why in plan.unresolved:
        print(
            f"UNRESOLVED id={r.id} player={r.player_id} date={r.game_date} "
            f"opp={r.opponent_team_id} reason={why}"
        )
    for r, d in plan.conflicts:
        print(
            f"CONFLICT id={r.id} player={r.player_id} date={r.game_date} -> {d} occupied"
        )
    for gone, kept in plan.box_mismatch:
        print(f"BOX_DIFFERS deleted={gone} kept={kept}")
    if applied:
        print(f"APPLIED: deleted {len(plan.deletes)}, moved {len(plan.moves)}")
    else:
        print("DRY RUN: nothing written (use --apply)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    parser.add_argument("--season", type=int, help="league start year, e.g. 2025")
    args = parser.parse_args()

    from scripts._db_script_guard import assert_not_local_default_db

    assert_not_local_default_db()

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        plan = plan_redate(load_rows(db, args.season), load_games(db))
        if args.apply:
            apply_plan(db, plan)
            db.commit()
        report(plan, args.apply)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
