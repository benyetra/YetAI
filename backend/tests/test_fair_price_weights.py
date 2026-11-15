"""Weights module: rows file, active() order, refit (SQLite + tmp files)."""

import json
from datetime import date

import pytest

from app.models.predictions_models import FairPriceWeights as W
from app.services.fair_price import weights as fw
from tests.auto_pick.conftest import sqlite_db  # noqa: F401  (fixture)

NBA, M = fw.NBA, "player_rebounds"
ROWS = {
    M: [
        ("2026-01", 1, {"a": 0.6, "b": 0.55}),
        ("2026-02", 0, {"b": 0.4, "a": 0.123456789}),
    ]
}


def test_rows_round_trip(tmp_path):
    p = tmp_path / "r.csv.gz"
    fw.write_rows(p, ROWS)
    got = fw.read_rows(p)
    assert got[M][0] == ("2026-01", 1, {"a": 0.6, "b": 0.55})
    assert got[M][1][2]["a"] == 0.123457


@pytest.fixture
def seed(tmp_path, monkeypatch):
    p = tmp_path / "seed.json"
    p.write_text(
        json.dumps(
            {
                "version": "seed-v",
                "sport": NBA,
                "markets": {M: {"weights": {"a": 2.0}, "fitted": ["a"], "n_rows": 1}},
            }
        )
    )
    monkeypatch.setattr(fw, "SEED_PATH", p)


def test_active_order(sqlite_db, seed):  # noqa: F811
    db = sqlite_db
    assert fw.active(db, NBA, M) == ({"a": 2.0}, "seed-v")
    assert fw.active(db, NBA, "player_points") == (None, fw.EQUAL)
    assert fw.active(db, "icehockey_nhl", M) == (None, fw.EQUAL)
    for v, through, wt in (
        ("v1", date(2026, 5, 31), 3.0),
        ("v2", date(2026, 6, 30), 4.0),
    ):
        db.add(
            W(version=v, sport=NBA, market=M, weights={"a": wt}, fitted_through=through)
        )
    db.commit()
    assert fw.active(db, NBA, M) == ({"a": 4.0}, "v2")
    assert fw.by_version(db, "v1", NBA, M) == {"a": 3.0}
    assert fw.by_version(db, "seed-v", NBA, M) == {"a": 2.0}
    assert fw.by_version(db, fw.EQUAL, NBA, M) is None
    assert fw.by_version(db, "nope", NBA, M) is None


def test_active_without_table(sqlite_db, seed):  # noqa: F811
    W.__table__.drop(sqlite_db.get_bind())
    assert fw.active(sqlite_db, NBA, M) == ({"a": 2.0}, "seed-v")
    assert fw.by_version(sqlite_db, "v1", NBA, M) is None


def test_refit_idempotent_and_versioned(sqlite_db, tmp_path, monkeypatch):  # noqa: F811
    db = sqlite_db
    hist = {
        M: [
            ("2026-01", i % 2, {"a": 0.55 if i % 2 else 0.45, "b": 0.5})
            for i in range(10)
        ]
    }
    fw.write_rows(tmp_path / "h.csv.gz", hist)
    monkeypatch.setattr(fw, "HISTORY_ROWS_PATH", tmp_path / "h.csv.gz")
    live = {M: [("2026-10", i % 2, {"a": 0.6, "b": 0.5}) for i in range(6)]}
    seen = {}

    def fake_close_rows(db_, start, end, markets):
        seen["args"] = (start, end)
        return live

    monkeypatch.setattr(fw, "close_rows", fake_close_rows)
    real_fit = fw.fit
    monkeypatch.setattr(fw, "fit", lambda rows: real_fit(rows, min_n=5))
    dry = fw.refit(db, date(2026, 12, 3), apply=False)
    assert db.query(W).count() == 0 and dry["status"] == "dry-run"
    out = fw.refit(db, date(2026, 12, 3))
    assert seen["args"] == (date(2026, 10, 1), date(2026, 11, 30))
    assert out["version"] == "nba-2026-11" and out["status"] == "applied"
    assert out["markets"][M] == {
        "history_rows": 10,
        "live_rows": 6,
        "fitted": ["a", "b"],
    }
    row = db.query(W).one()
    assert (row.version, row.n_rows, row.fitted_through, row.source) == (
        "nba-2026-11",
        16,
        date(2026, 11, 30),
        "history+live",
    )
    assert fw.refit(db, date(2026, 12, 20))["status"] == "exists"
    assert db.query(W).count() == 1


def test_refit_without_live_closes_keeps_seed(
    sqlite_db, tmp_path, monkeypatch
):  # noqa: F811
    hist = {M: [("2026-01", i % 2, {"a": 0.55, "b": 0.5}) for i in range(10)]}
    fw.write_rows(tmp_path / "h.csv.gz", hist)
    monkeypatch.setattr(fw, "HISTORY_ROWS_PATH", tmp_path / "h.csv.gz")
    monkeypatch.setattr(fw, "close_rows", lambda *a: {})
    real_fit = fw.fit
    monkeypatch.setattr(fw, "fit", lambda rows: real_fit(rows, min_n=5))
    out = fw.refit(sqlite_db, date(2026, 11, 15))
    assert out["markets"] == {} and sqlite_db.query(W).count() == 0
