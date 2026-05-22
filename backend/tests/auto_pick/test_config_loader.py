from unittest.mock import MagicMock

from app.services.auto_pick.config_loader import LoadedScoringConfig, load_scoring_config
from app.services.auto_pick.scoring_context import ScoringWeights


def _row(**overrides):
    defaults = dict(
        weight_edge=0.40, weight_historical=0.20, weight_freshness=0.15,
        weight_line_movement=0.10, weight_odds_sanity=0.10, weight_model_conf=0.05,
        score_threshold=65.0, odds_min=-300, odds_max=400, max_picks_per_day=4,
    )
    defaults.update(overrides)
    row = MagicMock()
    for k, v in defaults.items():
        setattr(row, k, v)
    return row


def _db_returning(row):
    db = MagicMock()
    db.query.return_value.order_by.return_value.first.return_value = row
    return db


def test_load_returns_defaults_when_no_row():
    cfg = load_scoring_config(_db_returning(None))
    assert isinstance(cfg, LoadedScoringConfig)
    assert isinstance(cfg.weights, ScoringWeights)
    assert cfg.score_threshold == 65.0
    assert cfg.odds_min == -300
    assert cfg.odds_max == 400
    assert cfg.max_picks == 4


def test_load_returns_row_values():
    row = _row(weight_edge=0.50, score_threshold=70.0, max_picks_per_day=3)
    cfg = load_scoring_config(_db_returning(row))
    assert cfg.weights.edge == 0.50
    assert cfg.score_threshold == 70.0
    assert cfg.max_picks == 3


def test_load_full_weights_passthrough():
    row = _row()
    cfg = load_scoring_config(_db_returning(row))
    w = cfg.weights
    assert (w.edge, w.historical, w.freshness, w.line_movement, w.odds_sanity, w.model_conf) == (
        0.40, 0.20, 0.15, 0.10, 0.10, 0.05,
    )
