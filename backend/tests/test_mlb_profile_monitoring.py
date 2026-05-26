"""Tests for profile monitoring helpers (Phase 8)."""

from datetime import date
from unittest.mock import MagicMock

from app.services.etl.mlb.profiles.monitoring import snapshot_coverage_report


def test_snapshot_coverage_report_empty_db():
    db = MagicMock()
    db.query.return_value.scalar.return_value = None
    db.query.return_value.filter.return_value.count.return_value = 0
    db.query.return_value.filter.return_value.limit.return_value.all.return_value = []

    report = snapshot_coverage_report(db)
    assert report["n_pitcher_snapshots"] == 0
    assert report["batter_reliability_coverage_pct"] == 0.0
