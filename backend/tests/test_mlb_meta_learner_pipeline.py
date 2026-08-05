"""Tests for MLB_META_LEARNER_ENABLED gate and pipeline apply hook."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_mlb_meta_learner_enabled_default_off(monkeypatch):
    from app.services.etl.mlb.meta_learner import mlb_meta_learner_enabled

    monkeypatch.delenv("MLB_META_LEARNER_ENABLED", raising=False)
    assert mlb_meta_learner_enabled() is False


def test_mlb_meta_learner_enabled_on(monkeypatch):
    from app.services.etl.mlb.meta_learner import mlb_meta_learner_enabled

    monkeypatch.setenv("MLB_META_LEARNER_ENABLED", "1")
    assert mlb_meta_learner_enabled() is True


def test_pipeline_applies_meta_when_enabled(monkeypatch):
    from app.services.etl.mlb import game_projection_pipeline as gpp

    monkeypatch.setenv("MLB_META_LEARNER_ENABLED", "1")

    preds = [
        {
            "game_id": 1,
            "home_team": "NYY",
            "away_team": "BOS",
            "home_win_prob": 0.55,
            "away_win_prob": 0.45,
        }
    ]

    def fake_apply(projections):
        for p in projections:
            p["home_win_prob"] = 0.62
            p["away_win_prob"] = 0.38
            p["meta_applied"] = True
        return projections

    with (
        patch.object(gpp, "fetch_game_odds", return_value={}),
        patch.object(gpp, "store_game_projections", return_value=1) as store,
        patch(
            "app.services.etl.mlb.meta_learner.apply_meta_learner",
            side_effect=fake_apply,
        ) as apply_meta,
        patch.object(gpp, "db_session") as db,
        patch(
            "app.services.etl.mlb.bullpen_fatigue.main",
            create=True,
        ),
        patch(
            "app.services.etl.mlb.game_model.load_park_factors",
        ),
        patch(
            "app.services.etl.mlb.game_model.get_todays_games",
            return_value=[{"game_id": 1}],
        ),
        patch(
            "app.services.etl.mlb.game_model.predict_games",
            return_value=preds,
        ),
        patch(
            "app.services.etl.mlb.monte_carlo.enrich_predictions_with_monte_carlo",
        ),
    ):
        db.query.return_value.all.return_value = []
        n = gpp.run_game_projection_pipeline()

    assert n == 1
    apply_meta.assert_called_once()
    stored_preds = store.call_args[0][0]
    assert stored_preds[0]["home_win_prob"] == 0.62
    assert stored_preds[0]["ml_recommendation"] == "HOME"


def test_pipeline_skips_meta_when_disabled(monkeypatch):
    from app.services.etl.mlb import game_projection_pipeline as gpp

    monkeypatch.setenv("MLB_META_LEARNER_ENABLED", "0")
    preds = [
        {
            "game_id": 1,
            "home_team": "NYY",
            "away_team": "BOS",
            "home_win_prob": 0.55,
            "away_win_prob": 0.45,
        }
    ]

    with (
        patch.object(gpp, "fetch_game_odds", return_value={}),
        patch.object(gpp, "store_game_projections", return_value=1),
        patch("app.services.etl.mlb.meta_learner.apply_meta_learner") as apply_meta,
        patch.object(gpp, "db_session") as db,
        patch(
            "app.services.etl.mlb.bullpen_fatigue.main",
            create=True,
        ),
        patch(
            "app.services.etl.mlb.game_model.load_park_factors",
        ),
        patch(
            "app.services.etl.mlb.game_model.get_todays_games",
            return_value=[{"game_id": 1}],
        ),
        patch(
            "app.services.etl.mlb.game_model.predict_games",
            return_value=preds,
        ),
        patch(
            "app.services.etl.mlb.monte_carlo.enrich_predictions_with_monte_carlo",
        ),
    ):
        db.query.return_value.all.return_value = []
        gpp.run_game_projection_pipeline()

    apply_meta.assert_not_called()
