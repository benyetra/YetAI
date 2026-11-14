"""NFL spread/totals game rows freeze at kickoff; a pulled line never blanks a stored one."""

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.etl._game_start import EASTERN
from app.services.etl.nfl import spread_projector, totals_projector
from app.services.etl.nfl import update_game_lines as ugl

KICK = datetime(2026, 11, 15, 18, 0)  # naive UTC = 1pm ET
BEFORE = datetime(2026, 11, 15, 17, 0, tzinfo=timezone.utc)
AFTER = datetime(2026, 11, 15, 19, 0, tzinfo=timezone.utc)


def _freeze(monkeypatch, now):
    class _Meta(type):
        def __instancecheck__(cls, obj):
            return isinstance(obj, datetime)

    class FakeDT(metaclass=_Meta):
        @staticmethod
        def now(tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr("app.services.etl._game_start.datetime", FakeDT)


def _event(commence, spread=-3.0, total=44.5):
    markets = []
    if spread is not None:
        markets.append(
            {
                "key": "spreads",
                "outcomes": [
                    {"name": "Home Team", "point": spread, "price": -110},
                    {"name": "Away Team", "point": -spread, "price": -110},
                ],
            }
        )
    if total is not None:
        markets.append(
            {
                "key": "totals",
                "outcomes": [
                    {"name": "Over", "point": total, "price": -110},
                    {"name": "Under", "point": total, "price": -110},
                ],
            }
        )
    return {
        "id": "ev1",
        "home_team": "Home Team",
        "away_team": "Away Team",
        "commence_time": commence,
        "bookmakers": [{"key": "pinnacle", "title": "Pinnacle", "markets": markets}],
    }


def _run_lines(monkeypatch, now, event, existing):
    _freeze(monkeypatch, now)
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = existing
    monkeypatch.setattr(ugl, "SessionLocal", lambda: db)
    monkeypatch.setattr(ugl, "_fetch_bulk_odds", lambda: [event])
    monkeypatch.setattr(ugl, "now_eastern", lambda: now.astimezone(EASTERN))
    monkeypatch.setattr(ugl, "normalize_game_teams", lambda h, a: (h, a))
    ugl.run()
    return db


def _stored():
    return SimpleNamespace(
        spread_home=-3.0, spread_away=3.0, spread_home_odds=-110,
        spread_away_odds=-110, total=44.5, over_odds=-110, under_odds=-110,
        moneyline_home=-150, moneyline_away=130, bookmaker="Pinnacle",
        odds_api_event_id="ev1", game_time=KICK, last_updated=None,
    )  # fmt: skip


def test_lines_started_game_live_line_ignored(monkeypatch):
    row = _stored()
    db = _run_lines(monkeypatch, AFTER, _event("2026-11-15T18:00:00Z", -7.5, 50.0), row)
    assert (row.spread_home, row.total) == (-3.0, 44.5)
    db.add.assert_not_called()


def test_lines_prestart_missing_market_keeps_line(monkeypatch):
    row = _stored()
    _run_lines(monkeypatch, BEFORE, _event("2026-11-15T18:00:00Z", None, None), row)
    assert (row.spread_home, row.total, row.over_odds) == (-3.0, 44.5, -110)


def test_lines_prestart_moved_line_updates(monkeypatch):
    row = _stored()
    _run_lines(monkeypatch, BEFORE, _event("2026-11-15T18:00:00Z", -4.0, 45.0), row)
    assert (row.spread_home, row.total) == (-4.0, 45.0)


def _game(**kw):
    base = dict(
        game_date=date(2026, 11, 15), game_time=KICK, home_team_id=1,
        away_team_id=2, home_team_name="Home Team", away_team_name="Away Team",
        spread_home=-3.0, total=44.5,
    )  # fmt: skip
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("mod", [spread_projector, totals_projector])
@pytest.mark.parametrize(
    "now,expected_rows", [(BEFORE, 1), (AFTER, 0)], ids=["prestart", "started"]
)
def test_projectors_skip_started_games(monkeypatch, mod, now, expected_rows):
    _freeze(monkeypatch, now)
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [_game()]
    db.query.return_value.order_by.return_value.all.return_value = []
    monkeypatch.setattr(mod, "SessionLocal", lambda: db)
    monkeypatch.setattr(mod, "now_eastern", lambda: now.astimezone(EASTERN))
    monkeypatch.setattr(mod, "_load_elos", lambda d: {})
    monkeypatch.setattr(mod, "_load_qb_out_by_team", lambda *a, **k: {})
    monkeypatch.setattr(mod, "compute_team_ppg_stats", lambda *a, **k: {})
    monkeypatch.setattr(mod, "team_ppg_for", lambda *a, **k: (22.0, 22.0))
    up = MagicMock()
    monkeypatch.setattr(mod, "upsert_many", up)
    mod.run()
    assert len(up.call_args.args[2]) == expected_rows
