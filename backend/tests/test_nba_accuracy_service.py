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


def test_daily_accuracy_returns_five_nba_buckets():
    db = _mock_db(
        {
            "PointsProjections": [
                _row(
                    player_id=1,
                    projected_points=18.0,
                    fanduel_line=17.5,
                    fanduel_over_under="over",
                )
            ],
            "PointsActuals": [SimpleNamespace(player_id=1, actual_points=20.0)],
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
    ]
    assert out["available"] is True
    # 18 over 17.5, actual 20 → correct
    pts = next(b for b in out["buckets"] if b["key"] == "points_ou")
    assert pts["primary"] == "1/1 · 100%"


def test_daily_accuracy_unavailable_when_no_rows():
    db = _mock_db({})
    out = svc.daily_accuracy(db, target_date=date(2026, 5, 23))
    assert out["available"] is False
    assert len(out["buckets"]) == 5


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
