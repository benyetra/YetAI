"""Integration smoke for mlb_accuracy_service.daily_accuracy.

Per-bucket math is covered by test_accuracy_shared. This file verifies
MLB rows feed into the right shared helpers and the assembled response
carries the expected bucket keys in order.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import mlb_accuracy_service as svc


def _proj_strikeout(
    pid="p1",
    projected_strikeouts=6.0,
    fd_line=5.5,
    fd_ou="over",
    model_version=None,
):
    return SimpleNamespace(
        pitcher_id=pid,
        projected_strikeouts=projected_strikeouts,
        fanduel_line=fd_line,
        fanduel_over_under=fd_ou,
        model_version=model_version,
    )


def _actual_strikeout(pid="p1", actual_strikeouts=7.0):
    return SimpleNamespace(
        pitcher_id=pid,
        actual_strikeouts=actual_strikeouts,
        actual_innings_pitched=6.0,
    )


D = date(2026, 5, 23)


def _proj_hits(projected_hits=2, actual_hits=1, batter_id=1, id=1):
    return SimpleNamespace(
        id=id,
        date=D,
        batter_id=batter_id,
        projected_hits=projected_hits,
        actual_hits=actual_hits,
    )


def _proj_homers(projected_homers=1, actual_homers=0, batter_id=1, id=1):
    return SimpleNamespace(
        id=id,
        date=D,
        batter_id=batter_id,
        projected_homers=projected_homers,
        actual_homers=actual_homers,
    )


def _batter_actual(batter_id=1):
    return SimpleNamespace(date=D, batter_id=str(batter_id))


def _game_projection(game_id=1):
    return SimpleNamespace(
        game_id=game_id,
        date=date(2026, 5, 23),
        home_team="Home",
        away_team="Away",
        home_win_prob=0.55,
        away_win_prob=0.45,
        projected_total=9.0,
        market_total=8.5,
        market_spread=-1.5,
        run_line=2.0,
        ml_recommendation="HOME",
        spread_recommendation="HOME",
        total_recommendation="OVER",
        __table__=SimpleNamespace(
            columns=[
                SimpleNamespace(name="game_id"),
                SimpleNamespace(name="ml_recommendation"),
                SimpleNamespace(name="spread_recommendation"),
                SimpleNamespace(name="total_recommendation"),
                SimpleNamespace(name="market_total"),
                SimpleNamespace(name="projected_total"),
                SimpleNamespace(name="market_spread"),
                SimpleNamespace(name="run_line"),
            ]
        ),
    )


def _game_actual(game_id=1):
    return SimpleNamespace(
        game_id=game_id,
        home_score=6,
        away_score=3,
        total_runs=9,
        winner="home",
        ml_correct=True,
        spread_correct=True,
        total_correct=True,
    )


def _mock_db(
    strikeouts,
    actuals,
    hits,
    homers,
    games=None,
    game_actuals=None,
    hit_actuals=None,
    homer_actuals=None,
):
    db = MagicMock()
    games = games or []
    game_actuals = game_actuals or []

    def query_side_effect(model):
        result = MagicMock()
        name = model.__name__
        if name == "StrikeoutProjections":
            result.filter.return_value.all.return_value = strikeouts
        elif name == "StrikeoutActuals":
            result.filter.return_value.all.return_value = actuals
        elif name == "ProjectedHits":
            result.filter.return_value.all.return_value = hits
        elif name == "ProjectedHomers":
            result.filter.return_value.all.return_value = homers
        elif name == "GameProjections":
            result.filter.return_value.all.return_value = games
        elif name == "GameActuals":
            result.filter.return_value.all.return_value = game_actuals
        elif name == "HitActuals":
            result.filter.return_value.all.return_value = hit_actuals or []
        elif name == "HomerActuals":
            result.filter.return_value.all.return_value = homer_actuals or []
        else:
            result.filter.return_value.all.return_value = []
        return result

    db.query.side_effect = query_side_effect
    return db


EXPECTED_KEYS = [
    "pitcher_ks_ou",
    "projected_hits",
    "projected_homers",
    "game_moneyline",
    "game_spread",
    "game_total",
]


def test_daily_accuracy_returns_six_buckets_in_order():
    db = _mock_db(
        strikeouts=[_proj_strikeout()],
        actuals=[_actual_strikeout()],
        hits=[_proj_hits(2, 1)],
        homers=[_proj_homers(1, 0)],
        games=[_game_projection()],
        game_actuals=[_game_actual()],
        hit_actuals=[_batter_actual()],
        homer_actuals=[_batter_actual()],
    )
    out = svc.daily_accuracy(db, target_date=date(2026, 5, 23))
    keys = [b["key"] for b in out["buckets"]]
    assert keys == EXPECTED_KEYS
    assert out["available"] is True
    assert out["date"] == "2026-05-23"


def test_daily_accuracy_marks_unavailable_when_no_rows():
    db = _mock_db(strikeouts=[], actuals=[], hits=[], homers=[])
    out = svc.daily_accuracy(db, target_date=date(2026, 5, 23))
    assert out["available"] is False
    assert len(out["buckets"]) == len(EXPECTED_KEYS)


def test_daily_accuracy_merges_strikeout_actuals_by_pitcher_id():
    db = _mock_db(
        strikeouts=[
            _proj_strikeout(pid="p1", fd_ou="over"),
            _proj_strikeout(pid="p2", projected_strikeouts=4.0, fd_ou="under"),
        ],
        actuals=[_actual_strikeout(pid="p1", actual_strikeouts=7.0)],
        hits=[],
        homers=[],
    )
    out = svc.daily_accuracy(db, target_date=date(2026, 5, 23))
    k_bucket = next(b for b in out["buckets"] if b["key"] == "pitcher_ks_ou")
    assert k_bucket["primary"] == "1/1 · 100%"


def test_daily_accuracy_groups_strikeouts_by_model_version():
    db = _mock_db(
        strikeouts=[
            _proj_strikeout(pid="p1", model_version="gb-v1"),
            _proj_strikeout(
                pid="p2",
                projected_strikeouts=4.0,
                fd_ou="under",
                model_version="heuristic-v1",
            ),
        ],
        actuals=[
            _actual_strikeout(pid="p1", actual_strikeouts=7.0),
            _actual_strikeout(pid="p2", actual_strikeouts=3.0),
        ],
        hits=[],
        homers=[],
    )
    out = svc.daily_accuracy(db, target_date=date(2026, 5, 23))
    by_v = out.get("strikeout_by_model_version")
    assert by_v is not None
    assert set(by_v) == {"gb-v1", "heuristic-v1"}
    assert by_v["gb-v1"]["primary"] == "1/1 · 100%"
    assert by_v["heuristic-v1"]["primary"] == "1/1 · 100%"


# --- MLB-4 / MLB-5 / H-3 / H-4 -------------------------------------------------


def _tile(out, key):
    return next(b for b in out["buckets"] if b["key"] == key)


def test_ungraded_batters_are_not_counted_as_misses():
    # actual_hits defaults to 0 on the projection row; no HitActuals row => ungraded.
    db = _mock_db(
        strikeouts=[],
        actuals=[],
        hits=[_proj_hits(2, 0, batter_id=1, id=1), _proj_hits(2, 3, batter_id=2, id=2)],
        homers=[],
        hit_actuals=[_batter_actual(2)],
    )
    out = svc.daily_accuracy(db, target_date=D)
    assert _tile(out, "projected_hits")["primary"].startswith("1/1")


def test_season_overview_excludes_batter_boards_from_headline():
    games = [_game_projection()]
    db = _mock_db(
        strikeouts=[],
        actuals=[],
        hits=[_proj_hits(2, 0)] * 5,
        homers=[_proj_homers(1, 0)] * 5,
        games=games,
        game_actuals=[_game_actual()],
        hit_actuals=[_batter_actual()],
        homer_actuals=[_batter_actual()],
    )
    out = svc.season_overview(db, start=D, end=D)
    names = {m["market"] for m in out["markets"]}
    assert names <= {
        "Pitcher Ks O/U",
        "Game moneyline",
        "Game spread",
        "Game total O/U",
    }
    assert out["graded_count"] == 3  # ML + spread + total, batter boards excluded

    diag = svc.season_overview_diagnostics(db, start=D, end=D)
    boards = [
        p for p in diag["parts"] if p["key"] in ("projected_hits", "projected_homers")
    ]
    assert boards and all(p["in_headline"] is False for p in boards)
    assert boards[0]["graded_total"] > 0  # still reported as their own counts
    assert diag["overview"]["graded_count"] == 3


def test_game_total_tile_excludes_no_play():
    g_over = _game_projection(1)
    g_none = _game_projection(2)
    g_none.total_recommendation = "NO_PLAY"
    db = _mock_db(
        strikeouts=[],
        actuals=[],
        hits=[],
        homers=[],
        games=[g_over, g_none],
        game_actuals=[_game_actual(1), _game_actual(2)],
    )
    out = svc.daily_accuracy(db, target_date=D)
    assert _tile(out, "game_total")["primary"].startswith("1/1")


def test_past_row_results_agree_with_tiles():
    ks = [
        _proj_strikeout(pid="p1", fd_ou="over"),  # actual 7 > 5.5 -> hit
        _proj_strikeout(pid="p2", fd_ou="under"),  # no actual, date graded -> dnp
    ]
    for i, k in enumerate(ks, start=1):
        k.id = i
    g = _game_projection(10)
    g.id = 100
    g.__table__.columns.append(SimpleNamespace(name="id"))
    db = _mock_db(
        strikeouts=ks,
        actuals=[_actual_strikeout(pid="p1", actual_strikeouts=7.0)],
        hits=[
            _proj_hits(2, 1, batter_id=1, id=11),  # graded hit
            _proj_hits(2, 0, batter_id=2, id=12),  # graded miss
            _proj_hits(2, 0, batter_id=3, id=13),  # no actuals row -> dnp
        ],
        homers=[],
        games=[g],
        game_actuals=[_game_actual(10)],
        hit_actuals=[
            SimpleNamespace(date=D, batter_id="1"),
            SimpleNamespace(date=D, batter_id="2"),
        ],
    )
    rows = svc.past_row_results(db, target_date=D)
    assert rows["strikeout_projections"][1] == {"actual": 7.0, "result": "hit"}
    assert rows["strikeout_projections"][2]["result"] == "dnp"
    h = {i: r["result"] for i, r in rows["projected_hits"].items()}
    assert h == {11: "hit", 12: "miss", 13: "dnp"}
    gr = rows["game_projections"][100]
    assert (gr["ml_result"], gr["spread_result"], gr["total_result"]) == (
        "hit",
        "hit",
        "hit",
    )
    assert gr["actual_home_score"] == 6 and gr["actual_total_runs"] == 9

    out = svc.daily_accuracy(db, target_date=D)
    assert _tile(out, "projected_hits")["primary"].startswith("1/2")
    assert _tile(out, "pitcher_ks_ou")["primary"].startswith("1/1")
    assert _tile(out, "game_moneyline")["primary"].startswith("1/1")
