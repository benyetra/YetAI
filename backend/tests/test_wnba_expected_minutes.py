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


def test_historical_expected_minutes_uses_recency_weights():
    target = date(2026, 6, 15)
    games = [
        _game(target - timedelta(days=i + 1), 36.0 if i == 0 else 24.0)
        for i in range(10)
    ]
    expected = em.historical_expected_minutes(games, game_date=target, home_game=None)
    minutes_l5 = (36.0 + 24.0 * 4) / 5
    assert expected is not None
    assert expected > minutes_l5


def test_historical_expected_minutes_b2b_context():
    target = date(2026, 6, 15)
    games = [_game(target - timedelta(days=i + 1), 30.0 - i) for i in range(6)]
    on_b2b = em.historical_expected_minutes(games, game_date=target, home_game=None)
    rested = em.historical_expected_minutes(
        games, game_date=target + timedelta(days=2), home_game=None
    )
    assert on_b2b is not None and rested is not None
    assert on_b2b < rested
