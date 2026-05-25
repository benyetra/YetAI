"""Strikeout ETL graceful degrade when classifier artifact is missing."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def strikeouts_module():
    """Import strikeouts without loading a classifier pickle at module init."""
    mock_pf = MagicMock()
    mock_pf.iterrows.return_value = [("park1", {"park_id": "park1", "hr_factor": 1.0})]
    module_name = "app.services.etl.mlb.strikeouts"
    sys.modules.pop(module_name, None)
    with (
        patch(
            "app.services.etl.mlb.strikeouts.read_csv_anywhere",
            return_value=mock_pf,
        ),
        patch(
            "app.services.etl.mlb.strikeouts.load_classifier",
            return_value=None,
        ),
    ):
        mod = importlib.import_module(module_name)
        yield mod


def test_strikeouts_imports_when_classifier_missing(strikeouts_module):
    assert strikeouts_module.over_under_clf is None


def test_get_over_under_classifier_returns_none_without_raise(strikeouts_module):
    strikeouts_module.over_under_clf = None
    with patch.object(
        strikeouts_module, "load_classifier", return_value=None
    ) as load_mock:
        clf = strikeouts_module._get_over_under_classifier()
    assert clf is None
    load_mock.assert_called_once()


def test_classifier_prob_over_heuristic_when_clf_missing(strikeouts_module):
    X = pd.DataFrame([{"projected_strikeouts": 6.5, "threshold": 5.5}])
    assert strikeouts_module.classifier_prob_over(
        None, X, proj_k_final=6.5, threshold=5.5
    ) == pytest.approx(1.0)
    assert strikeouts_module.classifier_prob_over(
        None, X, proj_k_final=4.0, threshold=5.5
    ) == pytest.approx(0.0)
    assert strikeouts_module.classifier_prob_over(
        None, X, proj_k_final=5.0, threshold=None
    ) == pytest.approx(0.5)


def test_classifier_prob_over_uses_model_when_present(strikeouts_module):
    clf = MagicMock()
    clf.predict_proba.return_value = np.array([[0.3, 0.7]])
    X = pd.DataFrame([{"projected_strikeouts": 6.0}])
    prob = strikeouts_module.classifier_prob_over(
        clf, X, proj_k_final=6.0, threshold=5.5
    )
    assert prob == pytest.approx(0.7)
    clf.predict_proba.assert_called_once_with(X)


def test_should_retrain_strikeout_classifier_guardrail():
    from app.services.etl.mlb.strikeout_training import (
        min_joined_rows,
        should_retrain_strikeout_classifier,
    )

    minimum = min_joined_rows()
    ready, reason = should_retrain_strikeout_classifier(
        {"joined": minimum - 1, "projections": 10, "actuals": 8}
    )
    assert ready is False
    assert str(minimum - 1) in reason

    ready, reason = should_retrain_strikeout_classifier(
        {"joined": minimum, "projections": 50, "actuals": 40}
    )
    assert ready is True
    assert str(minimum) in reason
