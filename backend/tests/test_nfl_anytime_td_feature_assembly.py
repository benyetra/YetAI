"""Tests for nflverse anytime-TD feature assembly (no network)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from app.services.etl.nfl.anytime_td_features import (
    _usage_as_of_week_for_priors,
    aggregate_defense_allowed_from_weekly,
    aggregate_player_usage_from_weekly,
    aggregate_team_rz_from_weekly,
    build_weekly_feature_rows,
    load_weekly_records_with_fallback,
    select_skill_universe,
)


def _weekly_sample() -> list[dict]:
    return [
        {
            "player_id": "rb1",
            "player_display_name": "Star RB",
            "position": "RB",
            "recent_team": "KC",
            "opponent_team": "BUF",
            "week": 1,
            "targets": 2,
            "carries": 15,
            "rushing_tds": 1,
            "receiving_tds": 0,
            "target_share": 0.1,
        },
        {
            "player_id": "rb1",
            "player_display_name": "Star RB",
            "position": "RB",
            "recent_team": "KC",
            "opponent_team": "CIN",
            "week": 2,
            "targets": 3,
            "carries": 18,
            "rushing_tds": 1,
            "receiving_tds": 1,
            "target_share": 0.12,
        },
        {
            "player_id": "wr1",
            "player_display_name": "Star WR",
            "position": "WR",
            "recent_team": "KC",
            "opponent_team": "BUF",
            "week": 1,
            "targets": 8,
            "carries": 0,
            "rushing_tds": 0,
            "receiving_tds": 1,
            "target_share": 0.28,
        },
        {
            "player_id": "wr1",
            "player_display_name": "Star WR",
            "position": "WR",
            "recent_team": "KC",
            "opponent_team": "CIN",
            "week": 2,
            "targets": 9,
            "carries": 0,
            "rushing_tds": 0,
            "receiving_tds": 0,
            "target_share": 0.3,
        },
        {
            "player_id": "buf_rb",
            "player_display_name": "Buf RB",
            "position": "RB",
            "recent_team": "BUF",
            "opponent_team": "KC",
            "week": 1,
            "targets": 1,
            "carries": 12,
            "rushing_tds": 0,
            "receiving_tds": 0,
            "target_share": 0.05,
        },
    ]


def test_aggregate_player_usage_prior_weeks_only():
    usage = aggregate_player_usage_from_weekly(_weekly_sample(), as_of_week=3)
    assert "rb1" in usage
    assert usage["rb1"]["td_season"] == 3.0
    assert usage["rb1"]["targets_l3"] > 0
    assert usage["rb1"]["conversion_rate"] is not None
    # week 3 row absent — as_of_week=3 excludes week>=3
    usage_w2 = aggregate_player_usage_from_weekly(_weekly_sample(), as_of_week=2)
    assert usage_w2["rb1"]["td_season"] == 1.0


def test_aggregate_team_and_defense():
    team = aggregate_team_rz_from_weekly(_weekly_sample(), as_of_week=3)
    assert "KC" in team
    assert team["KC"]["team_rz_trips"] >= 2.0
    defense = aggregate_defense_allowed_from_weekly(_weekly_sample(), as_of_week=3)
    # BUF allowed KC TDs in week 1 (RB 1 + WR 1)
    assert defense["BUF"]["RB"] >= 0
    assert defense["BUF"]["WR"] >= 0


def test_select_universe_includes_depth_and_usage():
    depth = [
        {
            "gsis_id": "rb1",
            "full_name": "Star RB",
            "position": "RB",
            "club_code": "KC",
            "depth_team": 1,
            "week": 3,
        },
        {
            "gsis_id": "qb1",
            "full_name": "QB One",
            "position": "QB",
            "club_code": "KC",
            "depth_team": 1,
            "week": 3,
        },
    ]
    usage = aggregate_player_usage_from_weekly(_weekly_sample(), as_of_week=3)
    universe = select_skill_universe(depth_records=depth, usage_by_player=usage, week=3)
    ids = {p["player_id"] for p in universe}
    assert "rb1" in ids
    assert "qb1" in ids
    assert "wr1" in ids  # from usage touches


def test_build_weekly_feature_rows_end_to_end_offline():
    schedules = [
        {
            "week": 3,
            "game_type": "REG",
            "home_team": "KC",
            "away_team": "BUF",
            "gameday": "2024-09-22",
            "roof": "outdoors",
            "wind": 10,
        }
    ]
    depth = [
        {
            "gsis_id": "rb1",
            "full_name": "Star RB",
            "position": "RB",
            "club_code": "KC",
            "depth_team": 1,
            "week": 3,
        },
        {
            "gsis_id": "wr1",
            "full_name": "Star WR",
            "position": "WR",
            "club_code": "KC",
            "depth_team": 1,
            "week": 3,
        },
    ]
    schemes = {
        "BUF": {
            "cover_base": "cover_3",
            "man_zone_lean": "zone",
            "pressure_lean": "medium",
        }
    }
    rows = build_weekly_feature_rows(
        2024,
        3,
        weekly_records=_weekly_sample(),
        schedule_records=schedules,
        depth_records=depth,
        schemes=schemes,
        game_lines_by_team={
            "KC": {
                "implied_total": 48.0,
                "spread": -3.0,
                "implied_team_total": 25.5,
            }
        },
    )
    assert len(rows) >= 2
    rb = next(r for r in rows if r["player_id"] == "rb1")
    assert rb["team_name"] == "Kansas City Chiefs"
    assert rb["opponent_team_name"] == "Buffalo Bills"
    assert rb["game_date"] == date(2024, 9, 22)
    assert rb["team_rz_trips"] > 0
    assert rb["defense_mult"] > 0
    assert rb["script_mult"] > 1.0
    assert rb["cover_base"] == "cover_3"


def test_usage_as_of_week_uses_all_prior_season_weeks():
    assert _usage_as_of_week_for_priors(season=2026, week=1, weekly_season=2024) == 99
    assert _usage_as_of_week_for_priors(season=2026, week=3, weekly_season=2026) == 3


def test_prior_season_usage_as_of_includes_week1_rows():
    """Week-1 target with prior-season weekly must not zero out usage."""
    usage = aggregate_player_usage_from_weekly(_weekly_sample(), as_of_week=99)
    assert "rb1" in usage
    assert usage["rb1"]["td_season"] >= 2


def test_load_weekly_records_falls_back_after_404():
    err = HTTPError(
        "https://example/2026.parquet", 404, "Not Found", hdrs=None, fp=None
    )

    class _FakeDf:
        def to_dict(self, orient="records"):
            assert orient == "records"
            return [{"player_id": "x", "week": 1, "position": "RB"}]

        def __len__(self):
            return 1

    nfl = MagicMock()

    def _import_weekly(years):
        y = years[0]
        if y >= 2025:
            raise err
        return _FakeDf()

    nfl.import_weekly_data.side_effect = _import_weekly

    with (
        patch("app.services.etl.nfl.anytime_td_features._import_nfl", return_value=nfl),
        patch(
            "app.services.etl.nfl.anytime_td_features._read_stats_player_week_parquet",
            side_effect=err,
        ),
    ):
        records, source = load_weekly_records_with_fallback(2026, max_lookback=3)

    assert source == 2024
    assert len(records) == 1
    assert nfl.import_weekly_data.call_count == 3  # 2026, 2025, 2024
