"""Smoke test for /api/v1/predictions/nfl endpoint."""

from datetime import date

from app.api.v1 import predictions as predictions_module
from app.models.predictions_models import QBPredictions


def test_nfl_route_exists():
    routes = [r for r in predictions_module.router.routes]
    paths = [r.path for r in routes]
    assert "/api/v1/predictions/nfl" in paths


def test_nfl_predictions_returns_all_expected_keys(monkeypatch):
    """The route should return qb, kicker, spreads, and totals (some may be empty)."""
    captured_models = []

    def fake_query_recent_nfl_with_fallback(
        db,
        model,
        date_col_name,
        target_date,
        limit,
        *,
        tz="UTC",
        dedupe_keys=None,
        latest_dedupe_keys=None,
    ):
        captured_models.append(model.__name__)
        return []

    def fake_enrich_prop_rows(rows, *, sport, stat, db):
        return rows

    def fake_attach_team_opponent_fields(rows):
        return rows

    def fake_attach_game_times(db, rows, _lines_model, **_kwargs):
        return rows

    monkeypatch.setattr(
        predictions_module,
        "_query_recent_nfl_with_fallback",
        fake_query_recent_nfl_with_fallback,
    )
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
    monkeypatch.setattr(
        predictions_module,
        "_query_nfl_anytime_td_predictions",
        lambda db, target_date, limit: [],
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
        "anytime_td_predictions",
        "spreads",
        "totals",
    }
    assert all(v == [] for v in result.values())
    assert "NFLSpreadProjections" in captured_models
    assert "NFLTotalsProjections" in captured_models
    assert "QBPredictions" in captured_models
    assert "KickerPredictions" in captured_models


def test_query_recent_nfl_with_fallback_uses_season_week(monkeypatch):
    """Off-season / pre-kickoff dates should fall back to current NFL week rows."""
    season_week_calls: list[tuple[int, int]] = []

    def fake_query_recent(
        db, model, date_col_name, target_date, limit, *, tz="UTC", dedupe_keys=None
    ):
        return []

    def fake_season_week(target_date):
        return 2026, 1

    def fake_by_season_week(db, model, season, week, limit, *, dedupe_keys=None):
        season_week_calls.append((season, week))
        return [
            {
                "qb_player_name": "Drake Maye",
                "season": season,
                "week": week,
                "qb_player_id": 1,
            }
        ]

    monkeypatch.setattr(predictions_module, "_query_recent", fake_query_recent)
    monkeypatch.setattr(predictions_module, "_nfl_slate_season_week", fake_season_week)
    monkeypatch.setattr(
        predictions_module, "_query_nfl_by_season_week", fake_by_season_week
    )

    rows = predictions_module._query_recent_nfl_with_fallback(
        None,
        QBPredictions,
        "game_date",
        date(2026, 8, 12),
        50,
        dedupe_keys=("season", "week", "qb_player_id"),
    )

    assert season_week_calls == [(2026, 1)]
    assert rows[0]["qb_player_name"] == "Drake Maye"
