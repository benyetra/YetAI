from unittest.mock import MagicMock, patch

from app.services.etl.wnba import backfill_shooting_columns as bsc


def test_dry_run_reports_pending_counts():
    mock_db = MagicMock()
    mock_db.execute.return_value.scalar.side_effect = [100, 200]
    with patch.object(bsc, "SessionLocal", return_value=mock_db):
        result = bsc.run(dry_run=True)
    assert result["status"] == "dry_run"
    assert result["efg_rows_pending"] == 100
    assert result["ts_rows_pending"] == 200
    mock_db.commit.assert_not_called()
