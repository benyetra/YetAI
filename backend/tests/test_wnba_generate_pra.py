"""Offline tests for WNBA PRA generator component wiring."""

from datetime import date
from unittest.mock import MagicMock, patch


def test_pra_run_writes_from_component_projections(monkeypatch):
    from app.services.etl.wnba import generate_pra_predictions as mod

    mock_db = MagicMock(name="Session")
    monkeypatch.setattr(mod, "SessionLocal", lambda: mock_db)

    active = MagicMock()
    active.player_id = 100
    active.player_name = "P1"
    active.team_name = "Home"
    active.opponent_team_name = "Away"
    active.opponent_team_id = 2
    active.game_date = date(2026, 6, 15)
    active.expected_minutes = 30.0

    recent = []
    for i in range(6):
        g = MagicMock()
        g.minutes = 30.0
        g.points = 15.0
        g.rebounds = 6.0
        g.assists = 4.0
        g.game_date = date(2026, 6, 10)
        recent.append(g)

    # active query → all; injury → None; recent → games; component queries → projected
    def query_side_effect(model):
        chain = MagicMock()
        name = getattr(model, "__name__", "")
        if "TodayActive" in name:
            chain.filter.return_value.all.return_value = [active]
        elif "Injury" in name:
            chain.filter.return_value.first.return_value = None
        elif "Recent" in name:
            chain.filter.return_value.order_by.return_value.limit.return_value.all.return_value = (
                recent
            )
        elif "Points" in name:
            row = MagicMock(projected_points=18.0)
            chain.filter.return_value.first.return_value = row
        elif "Rebounds" in name:
            row = MagicMock(projected_rebounds=7.0)
            chain.filter.return_value.first.return_value = row
        elif "Assists" in name:
            row = MagicMock(projected_assists=5.0)
            chain.filter.return_value.first.return_value = row
        else:
            chain.filter.return_value.all.return_value = []
            chain.filter.return_value.first.return_value = None
        return chain

    mock_db.query.side_effect = query_side_effect

    with (
        patch.object(mod, "attach_prop_market_fields", return_value=False),
        patch.object(mod, "attach_yetiwatch_news"),
        patch.object(mod, "upsert_many") as um,
        patch.object(mod, "resolve_wnba_event_id", return_value=None),
    ):
        result = mod.run()

    assert result["status"] == "ok"
    assert result["projections_written"] == 1
    row = um.call_args[0][2][0]
    # (18+7+5)*0.98 = 29.4
    assert row["projected_pra"] == 29.4
