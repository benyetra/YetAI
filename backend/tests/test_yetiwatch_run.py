"""Tests for YetiWatch run job (heuristic path, no Bedrock)."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from app.services.etl.yetiwatch.ingest import CandidateItem, SourceTier
from app.services.etl.yetiwatch.models import PlayerStatus
from app.services.etl.yetiwatch.heuristic import synthesize_heuristic


def test_heuristic_out_player():
    as_of = datetime.utcnow()
    items = [
        CandidateItem(
            tier=SourceTier.OFFICIAL,
            source_label="ESPN",
            item_ts=as_of,
            text="Out (knee)",
            player_name="Test Player",
        )
    ]
    payload = synthesize_heuristic(
        sport="wnba",
        run_id="test-run",
        as_of=as_of,
        entity_id=1,
        entity_name="Test Player",
        team_id=10,
        game_date=date.today(),
        opponent_id=20,
        items=items,
    )
    assert payload.status == PlayerStatus.OUT
    assert payload.impact.direction.value == "down"
    assert payload.news_string


@patch("app.services.etl.yetiwatch.run.bedrock_enabled", return_value=False)
@patch("app.services.etl.yetiwatch.run.get_adapter")
@patch("app.services.etl.yetiwatch.run.SessionLocal")
@patch("app.services.etl.yetiwatch.run.upsert_signals")
def test_run_empty_slate(mock_upsert, mock_session, mock_get_adapter, _bedrock):
    adapter = MagicMock()
    adapter.game_date.return_value = date.today()
    adapter.fetch_candidate_items.return_value = ([], True)
    adapter.load_slate.return_value = []
    adapter.apply_signals.return_value = {"status": "ok", "adjusted": 0}
    mock_get_adapter.return_value = adapter
    mock_session.return_value = MagicMock()

    from app.services.etl.yetiwatch.run import run_for_sport

    out = run_for_sport("wnba")
    assert out["status"] == "ok"
    assert out["entities"] == 0
    mock_upsert.assert_not_called()
