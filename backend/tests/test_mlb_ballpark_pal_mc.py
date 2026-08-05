from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.etl.mlb.monte_carlo import TeamRunRates


def test_bpp_run_priors_replace_lambdas_and_apply_park_factor(monkeypatch):
    from app.services.ballpark_pal import inject_game

    session = MagicMock()
    game = SimpleNamespace(team_home_id=136, team_away_id=108, bpp_game_id=776345)
    home = SimpleNamespace(averages_json={"runs": 5.2, "runsFirstFive": 2.8})
    away = SimpleNamespace(averages_json={"runs": 3.8, "runsFirstFive": 2.1})
    park = SimpleNamespace(factors_json={"runsPercent": 10})

    monkeypatch.setattr(inject_game, "ballpark_pal_enabled", lambda: True)
    monkeypatch.setattr(inject_game, "bpp_game_prior_weight", lambda: 1.0)
    monkeypatch.setattr(inject_game.store, "load_game_snapshot", lambda *args: game)
    monkeypatch.setattr(
        inject_game.store,
        "load_player_proj",
        lambda _session, team_id, _as_of, _role, **_kwargs: (
            home if team_id == game.team_home_id else away
        ),
    )
    monkeypatch.setattr(inject_game.store, "load_game_park_factor", lambda *args: park)

    rates, meta = inject_game.maybe_apply_bpp_run_priors(
        {},
        TeamRunRates(home_mu=4.4, away_mu=4.1),
        date(2026, 8, 5),
        game_id=776345,
        session=session,
    )

    assert rates == TeamRunRates(home_mu=5.72, away_mu=4.18)
    assert meta == {
        "applied": True,
        "weight": 1.0,
        "home_runs_prior": 5.2,
        "away_runs_prior": 3.8,
    }


def test_bpp_run_priors_soft_fail_without_snapshot(monkeypatch):
    from app.services.ballpark_pal import inject_game

    base = TeamRunRates(home_mu=4.4, away_mu=4.1)
    monkeypatch.setattr(inject_game, "ballpark_pal_enabled", lambda: True)
    monkeypatch.setattr(inject_game.store, "load_game_snapshot", lambda *args: None)

    rates, meta = inject_game.maybe_apply_bpp_run_priors(
        {},
        base,
        date(2026, 8, 5),
        game_id=776345,
        session=MagicMock(),
    )

    assert rates == base
    assert meta is None


def test_model_version_appends_bpp_after_mc():
    from app.services.etl.mlb.game_projection_pipeline import (
        _tag_game_projection_model_version,
    )

    predictions = [
        {
            "sim_distribution": {
                "matchup_meta": {"bpp": {"applied": True}},
            }
        }
    ]

    assert (
        _tag_game_projection_model_version("ensemble-v123456", predictions)
        == "ensemble-v123-mc-bpp"
    )
