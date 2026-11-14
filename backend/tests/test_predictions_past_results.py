"""Past-date prediction routes: per-row results, no live backfill, full NBA table."""

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.api.v1 import predictions as p
from app.services.etl.grading_window import eastern_today

PAST = eastern_today() - timedelta(days=2)


def _fake_service(monkeypatch, sport, results):
    mod = SimpleNamespace(past_row_results=lambda db, *, target_date: results)
    monkeypatch.setattr(
        p.importlib, "import_module", lambda name: mod if sport in name else None
    )


def test_merge_attaches_result_by_id_and_marks_missing_ungraded(monkeypatch):
    _fake_service(
        monkeypatch,
        "nba",
        {"points": {1: {"actual": 22, "result": "hit"}}},
    )
    payload = {"points": [{"id": 1}, {"id": 2}], "blocks": [{"id": 9}]}
    out = p._merge_past_results(payload, "nba", None, PAST)
    assert out["points"] == [
        {"id": 1, "actual": 22, "result": "hit"},
        {"id": 2, "result": "ungraded"},
    ]
    assert out["blocks"] == [{"id": 9}]  # market with no grading is untouched


def test_merge_leaves_today_and_default_view_unchanged(monkeypatch):
    _fake_service(monkeypatch, "nba", {"points": {1: {"result": "hit"}}})
    for d in (None, eastern_today(), eastern_today() + timedelta(days=1)):
        assert p._merge_past_results({"points": [{"id": 1}]}, "nba", None, d) == {
            "points": [{"id": 1}]
        }


def _mlb_db(meta, actuals=()):
    db = MagicMock()

    def query(model):
        q = MagicMock()
        q.all.return_value = [meta] if model.__name__ == "Pitcher" else list(actuals)
        q.filter.return_value.all.return_value = list(actuals)
        return q

    db.query.side_effect = query
    return db


def _run_mlb(monkeypatch, target_date):
    row = {
        "id": 5,
        "pitcher_id": "77",
        "pitcher_name": "A Pitcher",
        "date": PAST,
        "fanduel_line": None,
        "projected_strikeouts": 6.0,
    }
    meta = SimpleNamespace(
        pitcher_id="77",
        team="BOS",
        opponent="NYY",
        fanduel_point=5.5,
        fanduel_flag="over",
        prob_over=0.61,
        pick_edge_pct=7.0,
    )
    calls = iter([[row], [], [], [], []])
    monkeypatch.setattr(p, "_query_recent", lambda *a, **k: next(calls))
    monkeypatch.setattr(p, "attach_news_to_rows", lambda db, rows, **k: rows)
    monkeypatch.setattr(p, "attach_mlb_batter_team_opponent", lambda db, rows: rows)
    monkeypatch.setattr(p, "attach_team_opponent_fields", lambda rows: rows)
    monkeypatch.setattr(
        p, "enrich_strikeout_projection_row", lambda row, **kw: {**row, **kw}
    )
    monkeypatch.setattr(p, "enrich_strikeout_display_row", lambda row: row)
    _fake_service(monkeypatch, "mlb", {"strikeout_projections": {}})
    out = p.mlb_predictions(
        target_date=target_date,
        tz="UTC",
        limit=50,
        total_line=None,
        _user={"subscription_tier": "pro"},
        db=_mlb_db(meta),
    )
    return out["strikeout_projections"][0]


def test_past_strikeout_row_is_not_backfilled_from_live_pitcher_line(monkeypatch):
    row = _run_mlb(monkeypatch, PAST)
    assert row["fanduel_line"] is None
    assert row["fanduel_flag"] is None and row["prob_over"] is None
    assert row["result"] == "ungraded"


def test_today_strikeout_row_still_uses_live_pitcher_line(monkeypatch):
    row = _run_mlb(monkeypatch, None)
    assert row["fanduel_line"] == 5.5 and row["fanduel_flag"] == "over"


def test_past_nba_table_returns_every_row_deduped_by_player(monkeypatch):
    mk = lambda i, pid: {"id": i, "player_id": pid}  # noqa: E731
    rows = [mk(i, i) for i in range(1, 6)] + [mk(10, 1)]  # player 1 re-projected
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        SimpleNamespace(
            __table__=SimpleNamespace(
                columns=[SimpleNamespace(name="id"), SimpleNamespace(name="player_id")]
            ),
            **r,
        )
        for r in rows
    ]
    out = p._query_props_by_minutes(db, SimpleNamespace(date=1), PAST, 2, lambda *a: {})
    assert sorted(r["id"] for r in out) == [
        2,
        3,
        4,
        5,
        10,
    ]  # > limit, latest per player
    live = p._query_props_by_minutes(
        db, SimpleNamespace(date=1), eastern_today(), 2, lambda *a: {}
    )
    assert len(live) == 2
