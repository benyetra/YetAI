"""Smoke test for /api/v1/predictions/wnba endpoint."""

from datetime import date

from app.api.v1 import predictions as predictions_module


def test_wnba_route_exists():
    routes = [r for r in predictions_module.router.routes]
    paths = [r.path for r in routes]
    assert "/api/v1/predictions/wnba" in paths


def test_wnba_predictions_returns_all_expected_keys(monkeypatch):
    """The route should return totals, spreads, points, assists, rebounds (some may be empty)."""
    captured_models = []

    def fake_query_recent(
        db, model, date_col_name, target_date, limit, *, tz="UTC", dedupe_keys=None
    ):
        captured_models.append(model.__name__)
        return []

    def fake_enrich(db, spreads, totals, *, target_date=None):
        return spreads, totals

    monkeypatch.setattr(predictions_module, "_query_recent", fake_query_recent)
    monkeypatch.setattr(
        "app.services.wnba_game_picks.enrich_wnba_game_predictions",
        fake_enrich,
    )

    result = predictions_module.wnba_predictions(
        target_date=date(2026, 5, 21),
        tz="UTC",
        limit=50,
        _user={"subscription_tier": "pro"},
        db=None,
    )

    assert set(result.keys()) == {"totals", "spreads", "points", "assists", "rebounds"}
    assert all(v == [] for v in result.values())
    assert "WNBATotalsProjections" in captured_models
    assert "WNBASpreadProjections" in captured_models
    assert "WNBAPointsProjections" in captured_models
    assert "WNBAAssistsProjections" in captured_models
    assert "WNBAReboundsProjections" in captured_models


def test_wnba_predictions_enriches_spreads_with_actuals(monkeypatch):
    spread_row = {
        "game_date": date(2026, 5, 21),
        "home_team_name": "Indiana Fever",
        "away_team_name": "Golden State Valkyries",
        "recommendation": "HOME",
        "market_spread_home": -5.5,
    }

    def fake_query_recent(
        db, model, date_col_name, target_date, limit, *, tz="UTC", dedupe_keys=None
    ):
        if model.__name__ == "WNBASpreadProjections":
            return [dict(spread_row)]
        if model.__name__ == "WNBATotalsProjections":
            return []
        return []

    def fake_enrich(db, spreads, totals, *, target_date=None):
        enriched = [dict(spreads[0])]
        enriched[0]["actual_home_score"] = 90
        enriched[0]["actual_away_score"] = 82
        enriched[0]["spread_correct"] = True
        return enriched, totals

    monkeypatch.setattr(predictions_module, "_query_recent", fake_query_recent)
    monkeypatch.setattr(
        "app.services.wnba_game_picks.enrich_wnba_game_predictions",
        fake_enrich,
    )

    result = predictions_module.wnba_predictions(
        target_date=date(2026, 5, 21),
        tz="UTC",
        limit=50,
        _user={"subscription_tier": "pro"},
        db=None,
    )

    assert result["spreads"][0]["actual_home_score"] == 90
    assert result["spreads"][0]["spread_correct"] is True
