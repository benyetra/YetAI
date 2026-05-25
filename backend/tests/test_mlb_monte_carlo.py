"""Unit tests for MLB game-level Monte Carlo simulation."""

from app.services.etl.mlb.monte_carlo import (
    GameSimResult,
    expected_runs_from_features,
    expected_runs_from_projection,
    monte_carlo_enabled,
    p_over_total_for_game_row,
    probability_over_total,
    probability_over_total_at_line,
    resolve_team_rates,
    run_monte_carlo_backtest,
    simulate_game,
    TeamRunRates,
)


def _sample_features() -> dict:
    return {
        "home_recent_runs_avg": 5.0,
        "away_recent_runs_avg": 4.2,
        "home_starter_era": 4.1,
        "away_starter_era": 4.8,
        "park_factor": 1.05,
        "home_bullpen_fatigue": 0.4,
        "away_bullpen_fatigue": 0.6,
        "weather_run_adj": 0.2,
        "umpire_run_adj": 0.0,
        "home_ttop_adj": 0.0,
        "away_ttop_adj": 0.1,
        "injury_impact_home": 0.0,
        "injury_impact_away": 0.05,
        "home_travel_adj": 0.0,
        "away_travel_adj": 0.1,
    }


def test_expected_runs_from_features_positive():
    rates = expected_runs_from_features(_sample_features())
    assert rates.home_mu > 0
    assert rates.away_mu > 0


def test_expected_runs_from_projection_splits_total():
    rates = expected_runs_from_projection(8.5, 0.58)
    assert abs(rates.home_mu + rates.away_mu - 8.5) < 0.01
    assert rates.home_mu > rates.away_mu


def test_resolve_team_rates_blends():
    feat = expected_runs_from_features(_sample_features())
    blended = resolve_team_rates(
        _sample_features(),
        projected_total=9.0,
        home_win_prob=0.55,
        blend_ml=1.0,
    )
    pure_ml = expected_runs_from_projection(9.0, 0.55)
    assert blended.home_mu == pure_ml.home_mu
    assert blended.away_mu == pure_ml.away_mu
    zero_blend = resolve_team_rates(
        _sample_features(),
        projected_total=9.0,
        home_win_prob=0.55,
        blend_ml=0.0,
    )
    assert zero_blend.home_mu == feat.home_mu


def test_simulate_game_reproducible_with_seed():
    rates = TeamRunRates(home_mu=4.5, away_mu=4.0)
    a = simulate_game(rates, n_sims=5000, seed=99)
    b = simulate_game(rates, n_sims=5000, seed=99)
    assert a.home_win_prob == b.home_win_prob
    assert a.projected_total_mean == b.projected_total_mean


def test_simulate_game_win_prob_sanity():
    rates = TeamRunRates(home_mu=6.0, away_mu=3.0)
    sim = simulate_game(rates, n_sims=8000, seed=1)
    assert sim.home_win_prob > 0.65
    assert 6.0 < sim.projected_total_mean < 12.0
    assert "p50" in sim.percentiles_total
    assert sim.percentiles_total["p50"] > 0


def test_simulate_game_storage_dict_json_safe():
    sim = simulate_game(TeamRunRates(4.0, 4.0), n_sims=1000, seed=7)
    d = sim.to_storage_dict()
    assert d["n_sims"] == 1000
    assert isinstance(d["percentiles_total"], dict)


def test_probability_over_total_monotone():
    rates = TeamRunRates(home_mu=5.0, away_mu=4.5)
    assert probability_over_total_at_line(
        7.0, rates=rates, n_sims=6000, seed=11
    ) > probability_over_total_at_line(10.0, rates=rates, n_sims=6000, seed=11)


def test_p_over_total_for_game_row_uses_sim_lambdas():
    row = {
        "game_id": 999,
        "projected_total": 9.0,
        "home_win_prob": 0.52,
        "sim_distribution": {
            "home_lambda": 5.2,
            "away_lambda": 4.0,
            "dispersion": 1.35,
        },
    }
    p_low = p_over_total_for_game_row(row, 6.5, n_sims=4000, seed=1)
    p_high = p_over_total_for_game_row(row, 12.5, n_sims=4000, seed=1)
    assert p_low > p_high


def test_run_monte_carlo_backtest_returns_sidecar_fields():
    features = _sample_features()
    out = run_monte_carlo_backtest(features, 0.55, 8.5, game_id=1, n_sims=2000)
    assert "mc_home_wp" in out
    assert "mc_sim" in out
    assert out["mc_sim"]["home_lambda"] > 0


def test_monte_carlo_enabled_default_on(monkeypatch):
    monkeypatch.delenv("MLB_MC_ENABLED", raising=False)
    assert monte_carlo_enabled() is True


def test_monte_carlo_can_disable(monkeypatch):
    monkeypatch.setenv("MLB_MC_ENABLED", "0")
    assert monte_carlo_enabled() is False
