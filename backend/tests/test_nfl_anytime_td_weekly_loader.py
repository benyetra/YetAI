"""Tests for nflverse weekly loaders (legacy + stats_player_week) — no network."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from app.services.etl.nfl.anytime_td_features import (
    load_weekly_records_for_season,
    normalize_weekly_record,
)


def test_normalize_weekly_record_maps_team_to_recent_team():
    row = normalize_weekly_record(
        {
            "player_id": "p1",
            "team": "KC",
            "opponent_team": "BUF",
            "week": 3,
            "targets": 5,
            "carries": 0,
            "rushing_tds": 0,
            "receiving_tds": 1,
            "position": "WR",
        }
    )
    assert row["recent_team"] == "KC"
    assert row["team"] == "KC"
    assert row["opponent_team"] == "BUF"


def test_load_weekly_falls_back_to_stats_player_week_parquet():
    err = HTTPError(
        "https://example/player_stats_2025.parquet",
        404,
        "Not Found",
        hdrs=None,
        fp=None,
    )
    nfl = MagicMock()
    nfl.import_weekly_data.side_effect = err

    class _FakeDf:
        def to_dict(self, orient="records"):
            return [
                {
                    "player_id": "p1",
                    "team": "KC",
                    "opponent_team": "BUF",
                    "week": 1,
                    "position": "RB",
                    "targets": 1,
                    "carries": 10,
                    "rushing_tds": 1,
                    "receiving_tds": 0,
                    "target_share": 0.05,
                }
            ]

    with (
        patch("app.services.etl.nfl.anytime_td_features._import_nfl", return_value=nfl),
        patch(
            "app.services.etl.nfl.anytime_td_features._read_stats_player_week_parquet",
            return_value=_FakeDf(),
        ) as reader,
    ):
        records = load_weekly_records_for_season(2025)

    assert len(records) == 1
    assert records[0]["recent_team"] == "KC"
    reader.assert_called_once_with(2025)
