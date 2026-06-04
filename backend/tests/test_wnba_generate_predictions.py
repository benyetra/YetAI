from datetime import date
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.parametrize(
    "module_name,projection_cls_name,projected_col",
    [
        ("generate_points_predictions", "WNBAPointsProjections", "projected_points"),
        ("generate_assists_predictions", "WNBAAssistsProjections", "projected_assists"),
        (
            "generate_rebounds_predictions",
            "WNBAReboundsProjections",
            "projected_rebounds",
        ),
    ],
)
def test_inference_writes_projection_when_features_available(
    module_name, projection_cls_name, projected_col, monkeypatch
):
    from importlib import import_module

    mod = import_module(f"app.services.etl.wnba.{module_name}")

    mock_db = MagicMock(name="Session")
    monkeypatch.setattr(
        f"app.services.etl.wnba.{module_name}.SessionLocal", lambda: mock_db
    )

    active = MagicMock()
    active.player_id = 100
    active.player_name = "P1"
    active.team_name = "Home Team"
    active.opponent_team_id = 999
    active.opponent_team_name = "Opp"
    active.game_date = date(2026, 6, 15)
    active.expected_minutes = 30.0

    # No injury for this player
    mock_db.query.return_value.filter.return_value.all.return_value = [active]
    mock_db.query.return_value.filter.return_value.first.return_value = (
        None  # no injury row
    )

    with (
        patch(f"app.services.etl.wnba.{module_name}.build_features") as bf,
        patch(f"app.services.etl.wnba.{module_name}.predict") as pred,
        patch(f"app.services.etl.wnba.{module_name}.upsert_many") as um,
    ):
        bf.return_value = {"points_l5": 15.0}
        pred.return_value = 17.3
        result = mod.run()

    assert result["status"] == "ok"
    assert result["projections_written"] >= 1
    rows = um.call_args[0][2]
    assert rows[0]["player_id"] == 100
    assert rows[0][projected_col] == pytest.approx(17.3)
