"""Tests for game_projection_schedule helpers."""

from datetime import date, datetime

from app.services.game_projection_schedule import (
    attach_game_times,
    attach_game_times_from_lines,
    game_match_key,
)


class _FakeLine:
    def __init__(
        self,
        game_date: date,
        home_team_name: str,
        away_team_name: str,
        game_time: datetime | None,
    ):
        self.game_date = game_date
        self.home_team_name = home_team_name
        self.away_team_name = away_team_name
        self.game_time = game_time


class _FakeColumn:
    def in_(self, _values):
        return self


class _FakeModel:
    game_date = _FakeColumn()


class _FakeQuery:
    def __init__(self, rows: list[_FakeLine]):
        self._rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(self, rows: list[_FakeLine]):
        self._rows = rows

    def query(self, _model):
        return _FakeQuery(self._rows)


def test_game_match_key_normalizes_team_names():
    key = game_match_key(date(2026, 6, 7), " Chicago Sky ", "Indiana Fever")
    assert key == (date(2026, 6, 7), "chicago sky", "indiana fever")


def test_attach_game_times_merges_lookup():
    tip = datetime(2026, 6, 7, 19, 0, 0)
    lookup = {
        game_match_key(date(2026, 6, 7), "Cubs", "Giants"): tip,
    }
    rows = [
        {
            "game_date": date(2026, 6, 7),
            "home_team_name": "Cubs",
            "away_team_name": "Giants",
        }
    ]
    out = attach_game_times(rows, lookup)
    assert out[0]["game_time"] == tip


def test_attach_game_times_from_lines_uses_game_lines_table():
    tip = datetime(2026, 6, 7, 20, 10, 0)
    db = _FakeDb(
        [
            _FakeLine(date(2026, 6, 7), "Chicago Sky", "Indiana Fever", tip),
        ]
    )
    rows = [
        {
            "game_date": date(2026, 6, 7),
            "home_team_name": "Chicago Sky",
            "away_team_name": "Indiana Fever",
        }
    ]
    out = attach_game_times_from_lines(db, rows, _FakeModel)
    assert out[0]["game_time"] == tip
