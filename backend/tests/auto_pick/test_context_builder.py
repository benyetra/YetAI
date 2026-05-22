from datetime import datetime
from unittest.mock import MagicMock

from app.services.auto_pick.config_loader import LoadedScoringConfig
from app.services.auto_pick.context_builder import build_scoring_context
from app.services.auto_pick.scoring_context import ScoringContext, ScoringWeights


def _cfg():
    return LoadedScoringConfig(
        weights=ScoringWeights(),
        score_threshold=65.0,
        odds_min=-300,
        odds_max=400,
        max_picks=4,
    )


def _mock_db_no_data():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    db.query.return_value.filter.return_value.group_by.return_value.all.return_value = (
        []
    )
    db.query.return_value.all.return_value = []
    return db


def test_build_returns_scoring_context_with_passed_through_values():
    db = _mock_db_no_data()
    now = datetime(2026, 5, 22, 9, 0, 0)
    ctx = build_scoring_context(db, _cfg(), now)
    assert isinstance(ctx, ScoringContext)
    assert ctx.weights == _cfg().weights
    assert ctx.score_threshold == 65.0
    assert ctx.now == now


def test_build_returns_empty_dicts_when_no_data():
    db = _mock_db_no_data()
    ctx = build_scoring_context(db, _cfg(), datetime(2026, 5, 22))
    assert ctx.historical_hit_rates == {}
    assert ctx.line_movement == {}


def test_hit_rates_aggregated_from_settled_rows():
    """When the DB returns settled bet rows, hit rates are computed correctly."""
    db = MagicMock()

    # Simulate two groups: moneyline/nba (2W/1L = 0.667) and spread/nfl (1W/2L = 0.333)
    class FakeRow:
        def __init__(self, bet_type, sport, total, wins):
            self.bet_type = bet_type
            self.sport = sport
            self.total = total
            self.wins = wins

    fake_rows = [
        FakeRow("moneyline", "basketball_nba", 3, 2),
        FakeRow("spread", "americanfootball_nfl", 3, 1),
    ]

    # Chain: db.query(...).filter(...).group_by(...).all()
    db.query.return_value.filter.return_value.group_by.return_value.all.return_value = (
        fake_rows
    )

    ctx = build_scoring_context(db, _cfg(), datetime(2026, 5, 22))

    # Keys are normalized to (market_type, league) — matches what candidates emit.
    assert ("moneyline", "NBA") in ctx.historical_hit_rates
    assert abs(ctx.historical_hit_rates[("moneyline", "NBA")] - 2 / 3) < 1e-6
    assert ("spread", "NFL") in ctx.historical_hit_rates
    assert abs(ctx.historical_hit_rates[("spread", "NFL")] - 1 / 3) < 1e-6


def test_hit_rate_key_normalization_prop_to_player_prop():
    """BetType.PROP ('prop') must normalize to MarketType.PLAYER_PROP ('player_prop')."""
    db = MagicMock()

    class FakeRow:
        def __init__(self, bet_type, sport, total, wins):
            self.bet_type = bet_type
            self.sport = sport
            self.total = total
            self.wins = wins

    db.query.return_value.filter.return_value.group_by.return_value.all.return_value = [
        FakeRow("prop", "baseball_mlb", 10, 6),
    ]

    ctx = build_scoring_context(db, _cfg(), datetime(2026, 5, 22))

    assert ("player_prop", "MLB") in ctx.historical_hit_rates
    assert ("prop", "baseball_mlb") not in ctx.historical_hit_rates


def test_hit_rate_key_unknown_sport_passes_through():
    """If sport isn't in the normalization map, leave as-is (still queryable)."""
    db = MagicMock()

    class FakeRow:
        def __init__(self, bet_type, sport, total, wins):
            self.bet_type = bet_type
            self.sport = sport
            self.total = total
            self.wins = wins

    db.query.return_value.filter.return_value.group_by.return_value.all.return_value = [
        FakeRow("moneyline", "soccer_epl", 5, 3),
    ]

    ctx = build_scoring_context(db, _cfg(), datetime(2026, 5, 22))
    assert ("moneyline", "soccer_epl") in ctx.historical_hit_rates


def test_hit_rates_skips_zero_total_rows():
    """Rows with total == 0 must not cause a ZeroDivisionError."""
    db = MagicMock()

    class FakeRow:
        def __init__(self, bet_type, sport, total, wins):
            self.bet_type = bet_type
            self.sport = sport
            self.total = total
            self.wins = wins

    db.query.return_value.filter.return_value.group_by.return_value.all.return_value = [
        FakeRow("moneyline", "basketball_nba", 0, 0),
    ]

    ctx = build_scoring_context(db, _cfg(), datetime(2026, 5, 22))
    assert ctx.historical_hit_rates == {}


def test_line_movement_always_empty():
    """line_movement returns {} until an odds-movement pipeline is wired in."""
    db = _mock_db_no_data()
    ctx = build_scoring_context(db, _cfg(), datetime(2026, 5, 22))
    assert ctx.line_movement == {}
