from types import SimpleNamespace

from app.services.etl._spread_model import NFL_CONFIG
from app.services.etl.nfl.seed_elo import seed_elos_from_games


def test_nfl_config_thresholds():
    assert NFL_CONFIG.home_court_advantage == 2.5
    assert NFL_CONFIG.edge_threshold == 3.0


def test_seed_elos_from_chronological_games():
    games = [
        SimpleNamespace(
            home_team_name="Kansas City Chiefs",
            away_team_name="Baltimore Ravens",
            home_score=27,
            away_score=20,
        ),
        SimpleNamespace(
            home_team_name="Baltimore Ravens",
            away_team_name="Kansas City Chiefs",
            home_score=10,
            away_score=17,
        ),
    ]
    elos = seed_elos_from_games(games)
    assert elos["Kansas City Chiefs"] > elos["Baltimore Ravens"]
    assert abs(sum(elos.values()) - 2 * 1500) < 1e-6  # zero-sum updates from 1500
