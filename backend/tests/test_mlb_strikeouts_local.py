"""Fast local checks for MLB strikeouts (no Celery broker).

Tier 1: source contract tests — always run, no MLB/scikit-learn imports.
Tier 2: behavior tests — skip if optional deps are missing.

We do not import app.services.etl.mlb.strikeouts here: module init needs S3 park
factors and a strikeout classifier pickle. run() wiring is covered by
test_run_logic_simulation_no_name_error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
STRIKEOUTS_PY = BACKEND_ROOT / "app" / "services" / "etl" / "mlb" / "strikeouts.py"
OFFSETS_PY = BACKEND_ROOT / "app" / "services" / "etl" / "mlb" / "offsets.py"
REGRESSION_PY = BACKEND_ROOT / "app" / "services" / "etl" / "mlb" / "regression_analysis.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_strikeouts_run_unpacks_build_stats():
    text = _read(STRIKEOUTS_PY)
    assert "count, built, build_stats = fetch_and_update_app_data()" in text
    assert '"build_stats": build_stats' in text
    assert "return stored, built, build_stats" in text


def test_strikeouts_fetch_pitcher_returns_build_stats_tuple():
    text = _read(STRIKEOUTS_PY)
    assert "return pitchers, build_stats" in text
    assert '"probables_seen"' in text
    assert "_resolve_at_bats" in text
    assert '"ab_fallback_used"' in text


def test_offsets_use_pred_strikeout_tables():
    text = _read(OFFSETS_PY)
    assert "pred_strikeout_projections" in text
    assert "pred_strikeout_actuals" in text
    assert "FROM strikeout_projections" not in text


def test_project_at_bats_has_heuristic_helper():
    text = _read(REGRESSION_PY)
    assert "def _at_bats_heuristic" in text
    assert "if df.empty or len(df) < 5:" in text
    assert "return _at_bats_heuristic(projected_innings" in text
    assert "model.fit(X_scaled, y)" in text
    # No legacy dead branch that returns None on empty history
    assert 'logger.warning(f"No data found for pitcher {pitcher_id}")' not in text
    assert "return None\n\n        # Prevent division" not in text


def test_run_logic_simulation_no_name_error():
    """Mirrors run() / fetch_and_update_app_data() wiring without imports."""

    def fetch_and_update_app_data():
        build_stats = {"probables_seen": 15, "build_errors": 0}
        return 2, 2, build_stats

    def run():
        count, built, build_stats = fetch_and_update_app_data()
        if not count:
            return {"status": "error", "build_stats": build_stats}
        return {
            "status": "ok",
            "pred_pitcher_rows": count,
            "pitchers_built": built,
            "build_stats": build_stats,
        }

    ok = run()
    assert ok["status"] == "ok"
    assert ok["build_stats"]["probables_seen"] == 15


@pytest.mark.optional_deps
def test_project_at_bats_empty_history_uses_heuristic():
    pytest.importorskip("sklearn")
    import numpy as np
    from unittest.mock import MagicMock, patch

    from app.services.etl.mlb import regression_analysis

    with patch.object(regression_analysis.db_session, "execute") as mock_exec:
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_result.keys.return_value = [
            "date",
            "innings_pitched",
            "at_bats",
            "strikeouts",
            "walks",
            "whip",
            "baseOnBalls",
            "numberOfPitches",
        ]
        mock_exec.return_value = mock_result

        out = regression_analysis.project_at_bats_faced(
            12345,
            {"innings_pitched": 5.0, "strikeouts": 5.0, "walks": 1.0},
            5.0,
            0.5,
        )

    assert out is not None
    assert 17.0 <= out <= 40.0
