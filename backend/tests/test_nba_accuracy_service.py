"""Smoke tests for nba_accuracy_service.daily_accuracy.

Verifies row → bucket plumbing for the five NBA buckets. Bucket math is
covered by test_accuracy_shared.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import nba_accuracy_service as svc


def _row(**fields):
    """Tiny stand-in for a SQLAlchemy ORM row.

    Carries a __table__.columns iterable (each with a .name) plus regular
    attributes, which is all `_merge_actuals` walks to build row dicts.
    """
    cols = [SimpleNamespace(name=k) for k in fields.keys()]

    class _Row:
        pass

    obj = _Row()
    obj.__table__ = SimpleNamespace(columns=cols)
    for k, v in fields.items():
        setattr(obj, k, v)
    return obj


def _mock_db(rows_by_model: dict[str, list]):
    db = MagicMock()

    def query_side_effect(model):
        result = MagicMock()
        result.filter.return_value.all.return_value = rows_by_model.get(
            model.__name__, []
        )
        return result

    db.query.side_effect = query_side_effect
    return db


def test_daily_accuracy_returns_nba_buckets():
    db = _mock_db(
        {
            "PointsProjections": [
                _row(
                    id=1,
                    date=date(2026, 5, 23),
                    player_id=1,
                    projected_points=18.0,
                    fanduel_line=17.5,
                    fanduel_over_under="over",
                )
            ],
            "PointsActuals": [
                SimpleNamespace(player_id=1, date=date(2026, 5, 23), actual_points=20.0)
            ],
            "ThreePointProjections": [],
            "ActualThreePointMade": [],
            "StealsProjections": [],
            "StealsActuals": [],
            "AssistsProjections": [],
            "AssistsActuals": [],
            "ReboundsProjections": [],
            "ReboundsActuals": [],
        }
    )
    out = svc.daily_accuracy(db, target_date=date(2026, 5, 23))
    keys = [b["key"] for b in out["buckets"]]
    assert keys == [
        "points_ou",
        "three_pt_ou",
        "steals_ou",
        "assists_ou",
        "rebounds_ou",
        "pra_ou",
        "totals_ou",
        "spread_ats",
    ]
    assert out["available"] is True
    # 18 over 17.5, actual 20 → correct
    pts = next(b for b in out["buckets"] if b["key"] == "points_ou")
    assert pts["primary"] == "1/1 · 100%"


def test_daily_accuracy_unavailable_when_no_rows():
    db = _mock_db({})
    out = svc.daily_accuracy(db, target_date=date(2026, 5, 23))
    assert out["available"] is False
    assert len(out["buckets"]) == 8


def test_merge_actuals_range_keeps_latest_projection_per_player_date():
    projections = [
        _row(
            id=1,
            date=date(2026, 5, 23),
            player_id=7,
            projected_points=19.0,
            fanduel_line=18.5,
            fanduel_over_under="over",
        ),
        _row(
            id=2,
            date=date(2026, 5, 23),
            player_id=7,
            projected_points=21.0,
            fanduel_line=20.5,
            fanduel_over_under="under",
        ),
    ]
    actuals = [SimpleNamespace(player_id=7, date=date(2026, 5, 23), actual_points=20.0)]
    merged, stats = svc._merge_actuals_range(
        projections,
        actuals,
        pid_attr="player_id",
        actual_attr="actual_points",
        actual_key="actual_points",
    )
    assert len(merged) == 1
    assert stats["projection_rows_raw"] == 2
    assert stats["projection_rows_deduped"] == 1
    assert merged[0]["projected_points"] == 21.0
    assert merged[0]["fanduel_line"] == 20.5


# --- H-5/H-9/H-10/H-4/H-6: one fixture, tile == overview == row results -------
D = date(2026, 5, 23)


def _fixture_db():
    def prop(i, pid, line, pick, proj=20.0, **kw):
        return _row(
            id=i,
            date=D,
            player_id=pid,
            projected_points=proj,
            fanduel_line=line,
            fanduel_over_under=pick,
            **kw,
        )

    return _mock_db(
        {
            "PointsProjections": [
                prop(1, 1, 17.5, "over"),  # actual 20 -> hit
                prop(2, 2, 17.5, "over"),  # actual 10 -> miss
                prop(3, 3, 20.0, "under"),  # actual 20 -> push
                prop(4, 4, 17.5, "over"),  # no actual row -> dnp
                prop(5, 1, 17.5, "over"),  # dup of player 1 (latest id wins) -> hit
                prop(6, 6, 17.5, "PASS"),  # not a call
            ],
            "PointsActuals": [
                SimpleNamespace(player_id=1, date=D, actual_points=20.0),
                SimpleNamespace(player_id=2, date=D, actual_points=10.0),
                SimpleNamespace(player_id=3, date=D, actual_points=20.0),
                SimpleNamespace(player_id=6, date=D, actual_points=22.0),
            ],
            "PRAProjections": [
                _row(
                    id=1,
                    date=D,
                    player_id=1,
                    projected_pra=40.0,
                    fanduel_line=38.5,
                    fanduel_over_under="under",
                )
            ],
            "PRAActuals": [SimpleNamespace(player_id=1, date=D, actual_pra=45.0)],
            "NBATotalsProjections": [
                SimpleNamespace(
                    id=11,
                    game_date=D,
                    home_team_name="A",
                    away_team_name="B",
                    projected_total=225.0,
                    market_total=220.5,
                    recommendation="OVER",
                ),
                SimpleNamespace(
                    id=12,
                    game_date=D,
                    home_team_name="C",
                    away_team_name="D",
                    projected_total=210.0,
                    market_total=215.5,
                    recommendation="UNDER",
                ),
            ],
            "NBATotalsActuals": [
                SimpleNamespace(
                    game_date=D,
                    home_team_name="A",
                    away_team_name="B",
                    actual_total=230,
                    home_actual_score=120,
                    away_actual_score=110,
                ),
                SimpleNamespace(
                    game_date=D,
                    home_team_name="C",
                    away_team_name="D",
                    actual_total=220,
                    home_actual_score=110,
                    away_actual_score=110,
                ),
            ],
            "NBASpreadProjections": [
                SimpleNamespace(
                    id=21,
                    game_date=D,
                    home_team_name="A",
                    away_team_name="B",
                    projected_margin=6.0,
                    market_spread_home=-5.5,
                    recommendation="HOME",
                ),
                SimpleNamespace(
                    id=22,
                    game_date=D,
                    home_team_name="C",
                    away_team_name="D",
                    projected_margin=0.0,
                    market_spread_home=0.0,
                    recommendation="AWAY",
                ),
            ],
            "NBASpreadActuals": [
                SimpleNamespace(
                    game_date=D,
                    home_team_name="A",
                    away_team_name="B",
                    home_score=120,
                    away_score=110,
                    actual_margin=10,
                    home_won=True,
                ),
                SimpleNamespace(
                    game_date=D,
                    home_team_name="C",
                    away_team_name="D",
                    home_score=110,
                    away_score=110,
                    actual_margin=0,
                    home_won=False,
                ),
            ],
        }
    )


def test_tile_overview_and_rows_agree_on_one_fixture():
    db = _fixture_db()
    rows = svc.past_row_results(db, target_date=D)

    pts = {i: r["result"] for i, r in rows["points"].items()}
    # the duplicate pid is collapsed to the latest id (5): one row per player
    assert pts == {2: "miss", 3: "push", 4: "dnp", 5: "hit", 6: "no_play"}
    assert rows["pra"][1]["result"] == "miss"  # under 38.5, actual 45
    assert rows["totals"][11]["result"] == "hit"
    assert rows["totals"][12]["result"] == "miss"  # 220 vs 215.5 UNDER
    assert rows["spreads"][21]["result"] == "hit"  # home -5.5, won by 10
    assert rows["spreads"][22]["result"] == "push"  # margin 0 == threshold 0
    assert rows["totals"][11]["actual_home_score"] == 120
    assert rows["spreads"][21]["actual_away_score"] == 110

    # tiles count exactly the hits/misses of the rows
    tiles = {b["key"]: b for b in svc.daily_accuracy(db, target_date=D)["buckets"]}
    assert tiles["points_ou"]["primary"].startswith("1/2")
    assert "1 push" in tiles["points_ou"]["secondary"]
    assert tiles["pra_ou"]["primary"].startswith("0/1")
    assert tiles["totals_ou"]["primary"].startswith("1/2")
    assert tiles["spread_ats"]["primary"].startswith("1/1")

    # overview = same hits/misses summed over every market
    ov = svc.season_overview(db, start=D, end=D)
    got = {m["market"]: (m["correct"], m["graded"]) for m in ov["markets"]}
    assert got == {
        "Points O/U": (1, 2),
        "PRA O/U": (0, 1),
        "Game totals O/U": (1, 2),
        "Spreads ATS": (1, 1),
    }
    assert ov["graded_count"] == 6
