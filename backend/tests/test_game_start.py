from datetime import date, datetime, timezone

from app.services.etl._game_start import EASTERN, has_started, keep_known, not_started

NOW = datetime(2026, 11, 14, 0, 30, tzinfo=timezone.utc)  # 19:30 ET, Nov 13


def test_naive_utc_start_vs_now():
    assert has_started(datetime(2026, 11, 14, 0, 0), now=NOW)  # 19:00 ET tip
    assert not has_started(datetime(2026, 11, 14, 1, 0), now=NOW)  # 20:00 ET


def test_naive_eastern_start():
    assert has_started(datetime(2026, 11, 13, 19, 0), now=NOW, naive_tz=EASTERN)
    assert not has_started(datetime(2026, 11, 13, 22, 0), now=NOW, naive_tz=EASTERN)


def test_aware_start():
    start = datetime(2026, 11, 13, 19, 30, tzinfo=EASTERN)
    assert has_started(start, now=NOW)


def test_unknown_start_fails_safe_by_eastern_date():
    # 00:30 UTC is already Nov 14 in UTC but still Nov 13 in Eastern.
    assert not has_started(None, game_date=date(2026, 11, 13), now=NOW)
    assert has_started(None, game_date=date(2026, 11, 12), now=NOW)
    assert not has_started(None, now=NOW)
    assert has_started(date(2026, 11, 12), now=NOW)


def test_keep_known_never_writes_none_over_a_value():
    class Row:
        total = 221.5
        spread_home = None

    row = Row()
    keep_known(row, {"total": None, "spread_home": -3.5})
    assert row.total == 221.5 and row.spread_home == -3.5


def test_not_started_filters():
    games = [("a", datetime(2026, 11, 14, 0, 0)), ("b", datetime(2026, 11, 14, 2, 0))]
    kept = not_started(games, lambda g: (g[1], None), now=NOW)
    assert [g[0] for g in kept] == ["b"]
