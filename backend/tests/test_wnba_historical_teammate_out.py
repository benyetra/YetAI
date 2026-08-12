"""Tests for historical teammate-out minutes boost."""

from datetime import date, timedelta

from app.services.etl.wnba import _expected_minutes as em


def _game(d: date, minutes: float, *, home: bool | None = True):
    class Row:
        pass

    row = Row()
    row.game_date = d
    row.minutes = minutes
    row.home_game = home
    return row


def test_redistribute_minutes_boost_caps_and_shares():
    boost = em.redistribute_minutes_boost(
        30.0, freed_minutes=20.0, active_pool_total=100.0
    )
    # share = 30/100 = 0.3 → 6.0
    assert boost == 6.0
    capped = em.redistribute_minutes_boost(
        50.0, freed_minutes=100.0, active_pool_total=50.0
    )
    assert capped == em.MAX_TEAMMATE_BOOST


def test_historical_expected_minutes_applies_teammate_out_boost():
    target = date(2026, 6, 15)
    games = [_game(target - timedelta(days=i + 1), 32.0) for i in range(10)]
    base = em.historical_expected_minutes(games, game_date=target, home_game=True)
    boosted = em.historical_expected_minutes(
        games,
        game_date=target,
        home_game=True,
        freed_minutes=20.0,
        active_pool_total=80.0,
    )
    assert base is not None and boosted is not None
    assert boosted > base
    assert boosted - base <= em.MAX_TEAMMATE_BOOST


def test_infer_historical_freed_minutes_from_absences():
    game_date = date(2026, 6, 15)
    # Star teammate averaged 30 but has no box score on game_date
    teammate_avg = {101: 30.0, 102: 28.0, 103: 12.0}
    teammate_played = {101: False, 102: True, 103: True}
    freed = em.infer_historical_freed_minutes(
        player_id=200,
        teammate_avg_minutes=teammate_avg,
        teammate_played=teammate_played,
    )
    assert freed == 30.0  # only 101 (rotation + absent)
