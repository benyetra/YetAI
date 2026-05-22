import pytest

from app.services.etl._spread_model import (
    NBA_CONFIG,
    WNBA_CONFIG,
    update_elo,
    expected_margin,
)


def test_nba_hca_differs_from_wnba():
    assert NBA_CONFIG.home_court_advantage > WNBA_CONFIG.home_court_advantage


def test_update_elo_zero_sum():
    h, a = update_elo(1500, 1500, 110, 100, cfg=NBA_CONFIG)
    assert h > 1500
    assert a < 1500
    assert abs((h - 1500) + (a - 1500)) < 1e-6


def test_expected_margin_equal_elo_is_hca():
    assert expected_margin(1500, 1500, cfg=WNBA_CONFIG) == pytest.approx(
        WNBA_CONFIG.home_court_advantage
    )
