from datetime import date
from unittest.mock import MagicMock

from app.api.v1 import predictions as predictions_module
from app.services.player_prop_projection_display import enrich_nfl_recv_yds_row


def test_enrich_nfl_recv_yds_row_sets_edge_and_pick_keys():
    row = enrich_nfl_recv_yds_row(
        {
            "player_id": "1",
            "player_name": "A.J. Brown",
            "position": "WR",
            "predicted_receiving_yards": 85.0,
            "ou_line": 80.0,
            "betting_recommendation": "OVER",
            "edge_percentage": 6.25,
            "confidence_score": 0.8,
        }
    )
    assert row["predicted_receiving_yards"] == 85.0
    assert row["ou_line"] == 80.0
    assert "edge" in row
    assert (
        row.get("recommendation") == "OVER"
        or row.get("betting_recommendation") == "OVER"
    )


def test_nfl_predictions_includes_receiving_yards_key(monkeypatch):
    mock_db = MagicMock()

    def fake_query_recent(*args, **kwargs):
        model = args[1] if len(args) > 1 else kwargs.get("model")
        name = getattr(model, "__name__", "")
        if name == "RecvYdsPredictions":
            return [
                {
                    "player_id": "1",
                    "player_name": "A.J. Brown",
                    "position": "WR",
                    "team_name": "Philadelphia Eagles",
                    "opponent_team_name": "Dallas Cowboys",
                    "predicted_receiving_yards": 85.0,
                    "ou_line": 80.0,
                    "betting_recommendation": "OVER",
                    "prediction_method": "soft_anchor",
                    "game_date": date(2026, 11, 15),
                    "season": 2026,
                    "week": 11,
                }
            ]
        return []

    monkeypatch.setattr(
        predictions_module, "_query_recent_nfl_with_fallback", fake_query_recent
    )
    monkeypatch.setattr(
        predictions_module,
        "_query_nfl_anytime_td_predictions",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        "app.services.game_projection_schedule.attach_game_times_from_lines",
        lambda db, rows, model: rows,
    )

    monkeypatch.setattr(
        predictions_module,
        "enrich_prop_rows",
        lambda rows, **kwargs: rows,
    )
    monkeypatch.setattr(
        predictions_module,
        "attach_team_opponent_fields",
        lambda rows: rows,
    )

    out = predictions_module.nfl_predictions(
        target_date=date(2026, 11, 15),
        tz="UTC",
        limit=50,
        _user={"tier": "pro"},
        db=mock_db,
    )
    assert "receiving_yards_predictions" in out
    assert out["receiving_yards_predictions"][0]["prediction_method"] == "soft_anchor"
    assert out["receiving_yards_predictions"][0]["position"] == "WR"
