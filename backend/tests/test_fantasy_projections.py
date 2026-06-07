"""Unit tests for deterministic fantasy projections (ojg.5)."""

from app.services.fantasy_projections import (
    estimate_ownership_pct,
    generate_deterministic_projections,
)


def test_projections_use_position_baselines_when_no_db():
    players = [{"id": "9", "name": "Kicker", "position": "K", "team": "DAL"}]
    rows = generate_deterministic_projections(None, players, [], season=2024)
    assert rows[0]["projected_points"] == 7.0
    assert rows[0]["source"] == "baseline"


def test_ownership_estimate_is_bounded():
    value = estimate_ownership_pct(1001, 72.5)
    assert 5.0 <= value <= 85.0
