"""Yardsticks T1: same-row MAE, current-model record, new loaders, board row counts."""

from datetime import date, datetime, timedelta

from app.models import predictions_models as pm
from app.models.database_models import Game
from app.services import model_review_service as ms
from tests.auto_pick.conftest import sqlite_db  # noqa: F401  (fixture)

TODAY = date(2026, 11, 13)
YESTERDAY = TODAY - timedelta(days=1)


def _r(proj, line, actual, pick, day="2026-11-10", **extra):
    return ms._row(proj, line, actual, pick, ("t", day, "x"), "who", **extra)


def test_mae_uses_same_rows_and_all_mae_keeps_the_rest():
    rows = [
        _r(10.0, 12.0, 11.0, "over"),  # lined: model err 1, line err 1
        _r(10.0, None, 110.0, None),  # unlined, huge error
    ]
    s = ms.stats("ou", rows)
    assert (s["n"], s["mae"], s["line_mae"]) == (1, 1.0, 1.0)
    assert (s["all_n"], s["all_mae"]) == (2, 50.5)


def test_current_record_counts_newest_version_on_projection_side_at_real_prices():
    old = [_r(30.0, 20.5, 25.0, "over", day="2026-11-01", version="v1", price=-110)]
    new = [
        # hit on the projection side, real price
        _r(30.0, 20.5, 25.0, "over", version="v2", price=-120, best=None),
        # stored side contradicts the projection: graded over -> miss, no price for over
        _r(30.0, 20.5, 10.0, "under", day="2026-11-11", version="v2", price=-110),
        # projection says under (miss); stored side matches but has no price
        _r(10.0, 20.5, 25.0, "under", day="2026-11-11", version="v2", price=None),
        _r(20.5, 20.5, 25.0, "over", day="2026-11-11", version="v2", price=-110),
    ]
    c = ms._current_record("ou", old + new)
    assert (c["version"], c["first_date"]) == ("v2", "2026-11-10")
    assert (c["calls"], c["hits"], c["priced"]) == (3, 1, 1)
    assert c["units"] == 0.83  # only the priced hit at -120; nothing assumed at -110


def test_current_record_edge_uses_stored_call():
    rows = [_r(5.0, -3.0, 10.0, "HOME", correct=True, version="s1")]
    c = ms._current_record("edge", rows)
    assert (c["calls"], c["hits"], c["units"]) == (1, 1, None)


def _add_new_markets(db):
    db.add_all(
        [
            pm.PRAProjections(
                date=YESTERDAY,
                player_id=1,
                player_name="Pra Guy",
                opponent_team_name="X",
                projected_points=20,
                projected_rebounds=5,
                projected_assists=5,
                projected_pra=30.0,
                fanduel_line=28.5,
                fanduel_over_under="over",
            ),
            pm.PRAActuals(
                date=YESTERDAY,
                player_id=1,
                player_name="Pra Guy",
                opponent_team_name="X",
                actual_points=20,
                actual_rebounds=5,
                actual_assists=8,
                actual_pra=33.0,
            ),
            pm.NHLPlayerShotsPredictions(
                game_date=YESTERDAY,
                player_id=2,
                player_name="Shot Guy",
                team_name="A",
                opponent_team_name="B",
                predicted_shots=3.4,
                shots_line=2.5,
                betting_recommendation="OVER 2.5",
                prediction_date=datetime(2026, 11, 12, 15),
            ),
            pm.NHLPlayerShotsActuals(
                game_id=2026020100,
                game_date=YESTERDAY,
                player_id=2,
                player_name="Shot Guy",
                team_name="A",
                actual_shots=4,
            ),
            # preseason game (type 01): must not appear
            pm.NHLPlayerShotsPredictions(
                game_date=YESTERDAY,
                player_id=3,
                player_name="Pre Guy",
                team_name="A",
                opponent_team_name="B",
                predicted_shots=3.4,
                shots_line=2.5,
            ),
            pm.NHLPlayerShotsActuals(
                game_id=2026010001,
                game_date=YESTERDAY,
                player_id=3,
                player_name="Pre Guy",
                team_name="A",
                actual_shots=9,
            ),
            pm.NFLAnytimeTDPredictions(
                season=2026,
                week=10,
                game_date=YESTERDAY,
                player_id="p1",
                player_name="Td Guy",
                position="WR",
                team_name="A",
                opponent_team_name="B",
                expected_tds=0.6,
                td_probability=0.5,
                market_odds=120,
                market_implied_prob=0.4545,
                recommendation="OVER",
            ),
            pm.NFLAnytimeTDActuals(
                season=2026,
                week=10,
                game_date=YESTERDAY,
                player_id="p1",
                player_name="Td Guy",
                position="WR",
                team_name="A",
                opponent_team_name="B",
                scored_anytime_td=True,
                actual_td_count=1,
            ),
        ]
    )
    db.commit()


def test_pra_shots_and_anytime_td_loaders_feed_the_review(sqlite_db):  # noqa: F811
    _add_new_markets(sqlite_db)
    rows = ms.load_rows(sqlite_db, YESTERDAY, YESTERDAY)
    shots = rows[("NHL", "player_prop", "shots")][1]
    assert [r["label"] for r in shots] == ["Shot Guy"]  # preseason row dropped
    assert shots[0]["at"] == datetime(2026, 11, 12, 15)
    td = rows[("NFL", "player_prop", "anytime_td")][1][0]
    assert (td["actual"], td["over_price"], td["under_price"]) == (1.0, 120, None)

    text = ms.render_text(ms.build_review(sqlite_db, TODAY))
    for key in ("NBA/player_prop/pra", "NHL/player_prop/shots"):
        assert f"  {key}: 1/1 calls 100.0%" in text
    assert "  NFL/player_prop/anytime_td: 1/1 calls 100.0%" in text
    assert "current none since 2026-11-12" in text


def _game(db, i, day, sport="basketball_nba"):
    db.add(
        Game(
            id=f"{sport}-{day}-{i}",
            sport_key=sport,
            sport_title="s",
            home_team="H",
            away_team="A",
            commence_time=datetime(day.year, day.month, day.day, 23, 0),  # 6pm ET
        )
    )


def _points_rows(db, day, n):
    for i in range(n):
        db.add(
            pm.PointsProjections(
                date=day, player_id=i, player_name=f"P{i}", projected_points=10.0
            )
        )


def test_board_counts_flag_empty_and_thin_but_not_missing_schedule(
    sqlite_db,
):  # noqa: F811
    db = sqlite_db
    for d in range(1, 8):  # history: 1 game and 10 points rows a day
        day = YESTERDAY - timedelta(days=d)
        _game(db, 0, day)
        _points_rows(db, day, 10)
    for i in range(3):
        _game(db, i, YESTERDAY)
        _game(db, i, TODAY)
    _points_rows(db, TODAY, 12)  # 3 games x 10 = 30 expected, 12 written
    db.commit()

    bc = ms._board_counts_section(db, TODAY)
    by = {(k["date"], k["key"]): k for k in bc["keys"]}
    y, t = YESTERDAY.isoformat(), TODAY.isoformat()
    assert by[(y, "NBA/player_prop/points")]["flag"] == "empty"
    thin = by[(t, "NBA/player_prop/points")]
    assert (thin["flag"], thin["expected"], thin["games"]) == ("thin", 30.0, 3)
    assert by[(y, "NHL/player_prop/saves")]["flag"] == "no schedule"
    assert all(f["flag"] in ("empty", "thin") for f in bc["flagged"])
    assert not [f for f in bc["flagged"] if f["key"].startswith("NHL")]
    assert "== Board row counts ==" in ms.render_text(ms.build_review(db, TODAY))
