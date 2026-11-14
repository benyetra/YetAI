"""Smoke tests for wnba_accuracy_service.daily_accuracy.

Six buckets: game totals (O/U + MAE), spread (MAE), and three per-player
O/U buckets (points, assists, rebounds).
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import wnba_accuracy_service as svc


def _mock_db(rows_by_model):
    db = MagicMock()

    def side_effect(model):
        result = MagicMock()
        result.filter.return_value.all.return_value = rows_by_model.get(
            model.__name__, []
        )
        return result

    db.query.side_effect = side_effect
    return db


def test_returns_nine_wnba_buckets_in_order():
    today = date(2026, 5, 23)
    tot_p = SimpleNamespace(
        game_date=today,
        home_team_name="A",
        away_team_name="B",
        projected_total=162.0,
        market_total=160.5,
        recommendation="OVER",
    )
    tot_a = SimpleNamespace(
        game_date=today,
        home_team_name="A",
        away_team_name="B",
        actual_total=168,
    )
    sp_p = SimpleNamespace(
        game_date=today,
        home_team_name="A",
        away_team_name="B",
        projected_margin=4.5,
    )
    sp_a = SimpleNamespace(
        game_date=today,
        home_team_name="A",
        away_team_name="B",
        actual_margin=6,
    )
    pts_p = SimpleNamespace(
        player_id=100,
        projected_points=18.0,
        market_line=17.5,
        recommendation="OVER",
    )
    pts_a = SimpleNamespace(player_id=100, actual_points=20.0)
    ast_p = SimpleNamespace(
        player_id=101,
        projected_assists=5.0,
        market_line=4.5,
        recommendation="UNDER",
    )
    ast_a = SimpleNamespace(player_id=101, actual_assists=3.0)
    reb_p = SimpleNamespace(
        player_id=102,
        projected_rebounds=8.0,
        market_line=7.5,
        recommendation="OVER",
    )
    reb_a = SimpleNamespace(player_id=102, actual_rebounds=9.0)
    db = _mock_db(
        {
            "WNBATotalsProjections": [tot_p],
            "WNBATotalsActuals": [tot_a],
            "WNBASpreadProjections": [sp_p],
            "WNBASpreadActuals": [sp_a],
            "WNBAPointsProjections": [pts_p],
            "WNBAPointsActuals": [pts_a],
            "WNBAAssistsProjections": [ast_p],
            "WNBAAssistsActuals": [ast_a],
            "WNBAReboundsProjections": [reb_p],
            "WNBAReboundsActuals": [reb_a],
        }
    )
    out = svc.daily_accuracy(db, target_date=today)
    keys = [b["key"] for b in out["buckets"]]
    assert keys == [
        "totals_ou",
        "totals_mae",
        "spread_mae",
        "spread_ats",
        "player_points_ou",
        "player_assists_ou",
        "player_rebounds_ou",
        "player_three_pt_made_ou",
        "player_pra_ou",
    ]
    assert out["available"] is True
    # All three per-player picks won
    for k in (
        "player_points_ou",
        "player_assists_ou",
        "player_rebounds_ou",
        "player_three_pt_made_ou",
        "player_pra_ou",
    ):
        bucket = next(b for b in out["buckets"] if b["key"] == k)
        if k in ("player_three_pt_made_ou", "player_pra_ou"):
            # New Phase 3 buckets may be empty in this fixture
            assert bucket is not None
            continue
        assert bucket["primary"] == "1/1 · 100%"


def test_unavailable_when_no_rows():
    db = _mock_db({})
    out = svc.daily_accuracy(db, target_date=date(2026, 5, 23))
    assert out["available"] is False
    assert len(out["buckets"]) == 9


D = date(2026, 5, 23)


def _game(model_kind: str, i: int, **kw):
    base = dict(game_date=D, home_team_name=f"H{i}", away_team_name=f"A{i}", id=i)
    return SimpleNamespace(**base, **kw)


def _past_fixture():
    """4 spread rows (HOME hit, AWAY miss, HOME push, NO_PLAY), 3 totals rows, 3 points rows."""
    sp = [
        _game(
            "p", 1, projected_margin=5, market_spread_home=-3.0, recommendation="HOME"
        ),
        _game(
            "p", 2, projected_margin=-5, market_spread_home=-3.0, recommendation="AWAY"
        ),
        _game(
            "p", 3, projected_margin=5, market_spread_home=-3.0, recommendation="HOME"
        ),
        _game(
            "p",
            4,
            projected_margin=1,
            market_spread_home=-3.0,
            recommendation="NO_PLAY",
        ),
    ]
    sa = [
        _game("a", 1, actual_margin=7, home_score=90, away_score=83, home_won=True),
        _game("a", 2, actual_margin=7, home_score=90, away_score=83, home_won=True),
        _game("a", 3, actual_margin=3, home_score=88, away_score=85, home_won=True),
        _game("a", 4, actual_margin=7, home_score=90, away_score=83, home_won=True),
    ]
    tp = [
        _game("p", 1, projected_total=170, market_total=160.5, recommendation="OVER"),
        _game(
            "p", 2, projected_total=150, market_total=160.5, recommendation="NO_PLAY"
        ),
        _game("p", 3, projected_total=150, market_total=173.0, recommendation="OVER"),
    ]
    ta = [
        _game("a", 1, actual_total=173, home_score=90, away_score=83),
        _game("a", 2, actual_total=173, home_score=90, away_score=83),
        _game("a", 3, actual_total=173, home_score=90, away_score=83),
    ]
    pp = [
        SimpleNamespace(
            id=10,
            date=D,
            player_id=1,
            projected_points=20,
            market_line=18.5,
            recommendation="OVER",
        ),
        SimpleNamespace(
            id=11,
            date=D,
            player_id=2,
            projected_points=20,
            market_line=18.5,
            recommendation="OVER",
        ),
        SimpleNamespace(
            id=12,
            date=D,
            player_id=3,
            projected_points=20,
            market_line=18.5,
            recommendation="OVER",
        ),
    ]
    pa = [
        SimpleNamespace(date=D, player_id=1, actual_points=25.0),
        SimpleNamespace(date=D, player_id=2, actual_points=10.0),
    ]
    return _mock_db(
        {
            "WNBASpreadProjections": sp,
            "WNBASpreadActuals": sa,
            "WNBATotalsProjections": tp,
            "WNBATotalsActuals": ta,
            "WNBAPointsProjections": pp,
            "WNBAPointsActuals": pa,
        }
    )


def test_spread_ats_tile_excludes_push_and_no_play():
    """H-5: WNBA spread had MAE only; the ATS tile now counts hits/misses, not pushes."""
    out = svc.daily_accuracy(_past_fixture(), target_date=D)
    spread = next(b for b in out["buckets"] if b["key"] == "spread_ats")
    assert spread["primary"] == "1/2 · 50%"


def test_overview_includes_spread_ats_and_markets_population():
    """H-5/H-6: overview carries spread ATS plus the markets that make up the number."""
    item = svc.season_overview(_past_fixture(), start=D, end=D)
    by_market = {m["market"]: (m["correct"], m["graded"]) for m in item["markets"]}
    assert by_market["Spread ATS"] == (1, 2)
    assert by_market["Game totals O/U"] == (1, 1)  # NO_PLAY and push excluded
    assert by_market["Points O/U"] == (1, 2)
    assert item["graded_count"] == 5


def test_past_row_results_agree_with_tiles():
    """H-4: per-row results and the tiles count the same hits/misses."""
    db = _past_fixture()
    rows = svc.past_row_results(db, target_date=D)

    assert {i: r["result"] for i, r in rows["spreads"].items()} == {
        1: "hit",
        2: "miss",
        3: "push",
        4: "no_play",
    }
    assert rows["spreads"][1]["actual_home_score"] == 90
    assert rows["spreads"][1]["actual_winner"] == "home"
    assert {i: r["result"] for i, r in rows["totals"].items()} == {
        1: "hit",
        2: "no_play",
        3: "push",
    }
    assert rows["totals"][1]["actual_total"] == 173
    # a prop with no actual while grading ran for the date is a DNP, not "ungraded"
    assert {i: r["result"] for i, r in rows["points"].items()} == {
        10: "hit",
        11: "miss",
        12: "dnp",
    }

    tiles = {
        b["key"]: b["primary"] for b in svc.daily_accuracy(db, target_date=D)["buckets"]
    }
    for key, rk in (
        ("spread_ats", "spreads"),
        ("totals_ou", "totals"),
        ("player_points_ou", "points"),
    ):
        res = [r["result"] for r in rows[rk].values()]
        hits, misses = res.count("hit"), res.count("miss")
        assert tiles[key].startswith(f"{hits}/{hits + misses} ")
