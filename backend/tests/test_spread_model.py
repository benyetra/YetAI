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


def test_nba_win_prob_scale_is_fitted_and_other_leagues_unchanged():
    from app.services.etl._spread_model import NFL_CONFIG, margin_to_win_prob

    assert NBA_CONFIG.win_prob_logistic_scale == 6.6
    for cfg, edge in ((WNBA_CONFIG, 2.0), (NFL_CONFIG, 3.0)):
        assert cfg.win_prob_logistic_scale == 7.0
        assert cfg.edge_threshold == edge
        assert cfg.home_court_advantage == 2.5
        assert (cfg.initial_elo, cfg.elo_k, cfg.spread_per_elo) == (1500.0, 20.0, 25.0)
        assert (cfg.pace_overlay_factor, cfg.season_decay) == (0.15, 0.75)
        assert cfg.season_start_month == 5
        got = [margin_to_win_prob(m, cfg=cfg) for m in (-10, -3, 0, 3, 10)]
        assert got == pytest.approx(
            [
                0.1933213698023087,
                0.3944675127794143,
                0.5,
                0.6055324872205857,
                0.8066786301976913,
            ],
            abs=1e-12,
        )
