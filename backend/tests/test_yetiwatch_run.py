"""Tests for YetiWatch run job (heuristic path, no Bedrock)."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from app.services.etl.wnba.yetiwatch.ingest import CandidateItem, SourceTier
from app.services.etl.wnba.yetiwatch.models import PlayerStatus
from app.services.etl.wnba.yetiwatch.heuristic import synthesize_heuristic


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
        run_id="test-run",
        as_of=as_of,
        player_id=1,
        player_name="Test Player",
        team_id=10,
        game_date=date.today(),
        opponent_id=20,
        items=items,
    )
    assert payload.status == PlayerStatus.OUT
    assert payload.impact.direction.value == "down"
    assert payload.news_string


@patch("app.services.etl.wnba.yetiwatch.run.bedrock_enabled", return_value=False)
@patch("app.services.etl.wnba.yetiwatch.run.fetch_candidate_items")
@patch("app.services.etl.wnba.yetiwatch.run.SessionLocal")
@patch("app.services.etl.wnba.yetiwatch.run.apply_signals_to_slate")
@patch("app.services.etl.wnba.yetiwatch.run.upsert_many")
def test_run_empty_slate(mock_upsert, mock_apply, mock_session, mock_fetch, _bedrock):
    mock_fetch.return_value = ([], True)
    db = MagicMock()
    mock_session.return_value = db
    db.query.return_value.filter.return_value.all.return_value = []

    from app.services.etl.wnba.yetiwatch.run import run

    out = run()
    assert out["status"] == "ok"
    assert out["players"] == 0
    mock_upsert.assert_not_called()
