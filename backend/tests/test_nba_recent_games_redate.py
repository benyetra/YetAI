from datetime import date, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import RecentGames
from scripts.nba_recent_games_redate import apply_plan, plan_redate

D = date(2026, 1, 10)
A, B, C = 101, 102, 103  # team ids
_n = [0]


def d(n):
    return D + timedelta(days=n)


def row(player, day, opp, home=True, box=(30, 10, 5, 5), **kw):
    _n[0] += 1
    m, p, r, a = box
    return SimpleNamespace(
        id=kw.pop("id", _n[0]),
        player_id=player,
        game_date=day,
        opponent_team_id=opp,
        home_game=home,
        minutes=m,
        points=p,
        rebounds=r,
        assists=a,
        **kw,
    )


# (date, home, away); schedule ends d(10) so later rows are "beyond"
GAMES = [(d(10), 9, 8)]


def test_evening_game_filed_a_day_late_moves_back():
    r = row(1, d(1), B)  # A hosts B on d(0); stored under UTC d(1)
    plan = plan_redate([r], GAMES + [(d(0), A, B)])
    assert plan.moves == [(r.id, d(1), d(0))] and not plan.deletes


def test_matinee_on_stored_date_stays():
    r = row(1, d(0), B)
    plan = plan_redate([r], GAMES + [(d(0), A, B)])
    assert not plan.moves and not plan.deletes and not plan.unresolved


def test_duplicate_pair_collapses_to_true_date():
    late, right = row(1, d(1), B), row(1, d(0), B)
    plan = plan_redate([late, right], GAMES + [(d(0), A, B)])
    assert plan.deletes == [late.id] and not plan.moves and not plan.box_mismatch


def test_duplicate_prefers_api_game_id():
    late = row(1, d(1), B, api_game_id=7)
    right = row(1, d(0), B)
    plan = plan_redate([late, right], GAMES + [(d(0), A, B)])
    assert plan.deletes == [right.id] and plan.moves == [(late.id, d(1), d(0))]


def test_back_to_back_different_opponents_untouched():
    r1, r2 = row(1, d(0), B), row(1, d(1), C)
    plan = plan_redate([r1, r2], GAMES + [(d(0), A, B), (d(1), A, C)])
    assert not plan.moves and not plan.deletes and not plan.unresolved


def test_two_teams_differ_resolved_by_neighbour_team():
    # opp B away on d(0) vs team A, and on d(-1)... player's team differs per day
    games = GAMES + [(d(0), A, B), (d(-1), C, B)]
    anchor = row(1, d(2), 77, home=True)
    games += [(d(2), A, 77)]
    r = row(1, d(0), B)
    plan = plan_redate([anchor, r], games)
    assert not plan.unresolved and not plan.moves  # team A -> game on d(0)
    r2 = row(1, d(0), B)
    plan2 = plan_redate([r2], games)
    assert [w for _, w in plan2.unresolved] == ["team_unknown"]


GAMES2 = GAMES + [(d(0), A, B), (d(1), A, B)]  # same two teams, back to back


def test_two_game_set_by_occupancy_and_bucket():
    # stored d(1): candidates d(1), d(0). The player's other row (stored d(0), one
    # candidate) holds d(0) -> this one takes d(1) and stays.
    other = row(1, d(0), B, box=(9, 9, 9, 9))
    mine = row(1, d(1), B, box=(33, 22, 11, 2))
    plan = plan_redate([other, mine], GAMES2)
    assert not plan.unresolved and not plan.moves
    # d(1) held by a row stored d(2) (one candidate, moves to d(1)) -> mine2 takes d(0)
    held = row(1, d(2), B, box=(9, 9, 9, 9))
    mine2 = row(1, d(1), B, box=(33, 22, 11, 2))
    plan = plan_redate([held, mine2], GAMES2)
    assert sorted(plan.moves) == sorted([(held.id, d(2), d(1)), (mine2.id, d(1), d(0))])
    # bucket: p2 has no occupancy evidence, but the same-bucket row took d(0)
    p2 = row(2, d(1), B, box=(5, 5, 5, 5))
    plan = plan_redate([held, mine2, p2], GAMES2)
    assert (p2.id, d(1), d(0)) in plan.moves and not plan.unresolved


def test_unresolvable_two_game_set_reported_not_moved():
    r = row(1, d(1), B)
    plan = plan_redate([r], GAMES2)
    assert [w for _, w in plan.unresolved] == ["two_game_set"] and not plan.moves


def test_row_without_game_reported():
    r = row(1, d(1), 55)
    plan = plan_redate([r], GAMES2)
    assert [w for _, w in plan.unresolved] == ["no_game"]


def test_conflict_not_moved():
    late = row(1, d(1), B)  # true d(0), where an unresolved row sits
    blocker = row(1, d(0), 55)  # no_game
    plan = plan_redate([late, blocker], GAMES + [(d(0), A, B)])
    assert [r.id for r, _ in plan.conflicts] == [late.id] and not plan.moves


def test_rows_beyond_schedule_skipped():
    r = row(1, d(11), B)
    plan = plan_redate([r], GAMES)
    assert plan.skipped_beyond_schedule == 1 and not plan.moves and not plan.unresolved


def test_apply_round_trip_and_second_plan_empty():
    engine = create_engine("sqlite://")
    RecentGames.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    games = GAMES + [(d(0), A, B), (d(3), A, C)]
    db.add_all(
        [
            RecentGames(
                player_id=1, game_date=d(1), opponent_team_id=B, home_game=True
            ),
            RecentGames(
                player_id=1, game_date=d(0), opponent_team_id=B, home_game=True
            ),
            RecentGames(
                player_id=2, game_date=d(1), opponent_team_id=B, home_game=True
            ),
            RecentGames(
                player_id=2, game_date=d(4), opponent_team_id=C, home_game=True
            ),
        ]
    )
    db.commit()
    plan = plan_redate(db.query(RecentGames).all(), games)
    assert len(plan.deletes) == 1 and len(plan.moves) == 2
    apply_plan(db, plan)
    db.commit()
    got = sorted((r.player_id, r.game_date) for r in db.query(RecentGames))
    assert got == [(1, d(0)), (2, d(0)), (2, d(3))]
    again = plan_redate(db.query(RecentGames).all(), games)
    assert not again.moves and not again.deletes and not again.unresolved
