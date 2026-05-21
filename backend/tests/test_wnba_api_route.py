"""Smoke test for /api/v1/predictions/wnba endpoint."""
from datetime import date

from app.api.v1 import predictions as predictions_module


def test_wnba_route_exists():
    routes = [r for r in predictions_module.router.routes]
    paths = [r.path for r in routes]
    assert "/api/v1/predictions/wnba" in paths


def test_wnba_predictions_returns_all_expected_keys(monkeypatch):
    """The route should return totals, spreads, points, assists, rebounds (some may be empty)."""
    # Stub _query_recent so we don't need a DB
    captured_models = []

    def fake_query_recent(db, model, date_col_name, target_date, limit, *, tz="UTC", dedupe_keys=None):
        captured_models.append(model.__name__)
        return []

    monkeypatch.setattr(predictions_module, "_query_recent", fake_query_recent)

    result = predictions_module.wnba_predictions(
        target_date=date(2026, 5, 21),
        tz="UTC",
        limit=50,
        _user={"subscription_tier": "pro"},
        db=None,
    )

    assert set(result.keys()) == {"totals", "spreads", "points", "assists", "rebounds"}
    # Each value should be an empty list (stubbed)
    assert all(v == [] for v in result.values())
    assert "WNBATotalsProjections" in captured_models
    assert "WNBASpreadProjections" in captured_models
    assert "WNBAPointsProjections" in captured_models
    assert "WNBAAssistsProjections" in captured_models
    assert "WNBAReboundsProjections" in captured_models
