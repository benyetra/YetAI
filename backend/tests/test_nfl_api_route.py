"""Smoke test for /api/v1/predictions/nfl endpoint."""

from datetime import date

from app.api.v1 import predictions as predictions_module


def test_nfl_route_exists():
    routes = [r for r in predictions_module.router.routes]
    paths = [r.path for r in routes]
    assert "/api/v1/predictions/nfl" in paths


def test_nfl_predictions_returns_all_expected_keys(monkeypatch):
    """The route should return qb, kicker, spreads, and totals (some may be empty)."""
    captured_models = []

    def fake_query_recent(
        db, model, date_col_name, target_date, limit, *, tz="UTC", dedupe_keys=None
    ):
        captured_models.append(model.__name__)
        return []

    def fake_enrich_prop_rows(rows, *, sport, stat, db):
        return rows

    def fake_attach_team_opponent_fields(rows):
        return rows

    def fake_attach_game_times(db, rows, _lines_model, **_kwargs):
        return rows

    monkeypatch.setattr(predictions_module, "_query_recent", fake_query_recent)
    monkeypatch.setattr(predictions_module, "enrich_prop_rows", fake_enrich_prop_rows)
    monkeypatch.setattr(
        predictions_module,
        "attach_team_opponent_fields",
        fake_attach_team_opponent_fields,
    )
    monkeypatch.setattr(
        "app.services.game_projection_schedule.attach_game_times_from_lines",
        fake_attach_game_times,
    )

    result = predictions_module.nfl_predictions(
        target_date=date(2026, 9, 7),
        tz="UTC",
        limit=50,
        _user={"subscription_tier": "pro"},
        db=None,
    )

    assert set(result.keys()) == {
        "qb_predictions",
        "kicker_predictions",
        "spreads",
        "totals",
    }
    assert all(v == [] for v in result.values())
    assert "NFLSpreadProjections" in captured_models
    assert "NFLTotalsProjections" in captured_models
    assert "QBPredictions" in captured_models
    assert "KickerPredictions" in captured_models
