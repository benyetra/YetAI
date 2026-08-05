"""Tests for persisting K matchup_source and classifier load probe."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def test_strikeouts_persists_matchup_source_on_pitcher_dict():
    text = (BACKEND / "app/services/etl/mlb/strikeouts.py").read_text(encoding="utf-8")
    assert '"matchup_source": matchup_source' in text
    assert 'matchup_source=pitcher_stats_data.get("matchup_source")' in text


def test_store_projections_copies_matchup_source_from_pitcher():
    from app.services.etl.mlb import daily_projection_update as dpu

    existing = SimpleNamespace(
        projected_strikeouts=0.0,
        projected_innings_pitched=0.0,
        projected_at_bats=0.0,
        fanduel_line=None,
        fanduel_over_under=None,
        matchup_source=None,
    )
    pitcher = SimpleNamespace(
        pitcher_id="123",
        name="Test",
        projected_innings=5.0,
        projected_at_bats=20.0,
        projected_strikeouts=6.0,
        fanduel_point=5.5,
        fanduel_flag="o",
        matchup_source="observed",
        prob_over=0.6,
        pick_edge_pct=4.0,
    )

    session = MagicMock()
    pitcher_q = MagicMock()
    pitcher_q.all.return_value = [pitcher]
    so_filter = MagicMock()
    so_filter.delete.return_value = 0
    so_filter_by = MagicMock()
    so_filter_by.first.return_value = existing
    so_q = MagicMock()
    so_q.filter.return_value = so_filter
    so_q.filter_by.return_value = so_filter_by

    def query_side(model):
        if model is dpu.Pitcher:
            return pitcher_q
        return so_q

    session.query.side_effect = query_side

    with (
        patch.object(dpu, "db_session", session),
        patch.object(
            dpu, "resolve_mlb_strikeout_model_version", return_value="test-v1"
        ),
        patch.object(dpu, "attach_model_version"),
        patch.object(dpu, "projection_pick_side", return_value="o"),
        patch.object(dpu, "ev_pick_from_flag", return_value="o"),
        patch.object(dpu, "pick_confidence_pct", return_value=55.0),
    ):
        dpu.store_projections(date(2026, 8, 5))

    assert existing.matchup_source == "observed"


def test_probe_classifier_load_reports_local_ok(tmp_path, monkeypatch):
    joblib = pytest.importorskip("joblib")
    pytest.importorskip("sklearn")
    from sklearn.linear_model import LogisticRegression

    from app.services.etl.mlb import classification_model as cm

    clf = LogisticRegression()
    path = tmp_path / "strikeout_model.pkl"
    joblib.dump(clf, path)
    monkeypatch.setattr(cm, "MODEL_LOCAL_PATH", str(path))

    result = cm.probe_classifier_load()
    assert result["ok"] is True
    assert result["source"] == "local"
    assert result["estimator_type"] == "LogisticRegression"
    assert result["error"] is None


def test_probe_classifier_load_reports_s3_failure(monkeypatch):
    pytest.importorskip("sklearn")
    import boto3

    from app.services.etl.mlb import classification_model as cm

    monkeypatch.setattr(cm, "MODEL_LOCAL_PATH", "/tmp/definitely-missing-strikeout.pkl")
    monkeypatch.setattr(
        boto3,
        "client",
        lambda *_a, **_k: MagicMock(
            get_object=MagicMock(side_effect=RuntimeError("no s3"))
        ),
    )

    result = cm.probe_classifier_load()
    assert result["ok"] is False
    assert "no s3" in (result.get("error") or "")
