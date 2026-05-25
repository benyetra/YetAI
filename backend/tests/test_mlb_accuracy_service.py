"""Integration smoke for mlb_accuracy_service.daily_accuracy.

Per-bucket math is covered by test_accuracy_shared. This file verifies
MLB rows feed into the right shared helpers and the assembled response
carries the three expected bucket keys in order.
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


def _proj_hits(projected_hits=2, actual_hits=1):
    return SimpleNamespace(projected_hits=projected_hits, actual_hits=actual_hits)


def _proj_homers(projected_homers=1, actual_homers=0):
    return SimpleNamespace(
        projected_homers=projected_homers, actual_homers=actual_homers
    )


def _mock_db(strikeouts, actuals, hits, homers):
    db = MagicMock()

    def query_side_effect(model):
        result = MagicMock()
        if "StrikeoutProjections" in model.__name__:
            result.filter.return_value.all.return_value = strikeouts
        elif "StrikeoutActuals" in model.__name__:
            result.filter.return_value.all.return_value = actuals
        elif "ProjectedHits" in model.__name__:
            result.filter.return_value.all.return_value = hits
        elif "ProjectedHomers" in model.__name__:
            result.filter.return_value.all.return_value = homers
        else:
            result.filter.return_value.all.return_value = []
        return result

    db.query.side_effect = query_side_effect
    return db


def test_daily_accuracy_returns_three_buckets_in_order():
    db = _mock_db(
        strikeouts=[_proj_strikeout()],
        actuals=[_actual_strikeout()],
        hits=[_proj_hits(2, 1)],
        homers=[_proj_homers(1, 0)],
    )
    out = svc.daily_accuracy(db, target_date=date(2026, 5, 23))
    keys = [b["key"] for b in out["buckets"]]
    assert keys == ["pitcher_ks_ou", "projected_hits", "projected_homers"]
    assert out["available"] is True
    assert out["date"] == "2026-05-23"


def test_daily_accuracy_marks_unavailable_when_no_rows():
    db = _mock_db(strikeouts=[], actuals=[], hits=[], homers=[])
    out = svc.daily_accuracy(db, target_date=date(2026, 5, 23))
    assert out["available"] is False
    assert len(out["buckets"]) == 3


def test_daily_accuracy_merges_strikeout_actuals_by_pitcher_id():
    """Strikeout row sent to the O/U bucket has actual pulled from
    StrikeoutActuals — not from the projection — even when only some
    pitchers have actuals recorded.
    """
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
    # p1: pick over 5.5, actual 7 → correct. p2: no actual → dropped.
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
