"""Tests for WNBA totals projection replay and backfill."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from app.services.etl.wnba.ml_training import backfill_totals_projections as btp
from app.services.etl.wnba.ml_training import team_stats_as_of as tsa
from app.services.etl.wnba.ml_training.replay_totals_projection import (
    generate_projection_as_of,
)


def test_generate_projection_as_of_uses_point_in_time_stats():
    cache = tsa.TeamStatsCache(
        team_name_to_id={"home": 1, "away": 2},
        by_team={
            1: [
                (
                    date(2024, 5, 1),
                    {
                        "pace": 80.0,
                        "offensive_rating": 105.0,
                        "defensive_rating": 100.0,
                    },
                )
            ],
            2: [
                (
                    date(2024, 5, 1),
                    {
                        "pace": 78.0,
                        "offensive_rating": 101.0,
                        "defensive_rating": 99.0,
                    },
                )
            ],
        },
    )

    with patch("app.services.etl.wnba.totals_projector.db", MagicMock()):
        with patch(
            "app.services.etl.wnba.totals_projector.calculate_rest_adjustment",
            return_value=0.0,
        ):
            with patch(
                "app.services.etl.wnba.totals_projector.calculate_form_adjustment_as_of",
                return_value=0.0,
            ):
                proj = generate_projection_as_of(
                    home_team="Home",
                    away_team="Away",
                    game_date=date(2024, 6, 1),
                    market_total=165.0,
                    stats_cache=cache,
                )

    assert proj["projected_total"] > 0
    assert proj["factors"]["ml_shadow"]["heuristic_total"] == proj["projected_total"]
    assert proj["market_total"] == 165.0


def test_backfill_skips_existing_without_force():
    mock_db = MagicMock()
    existing_key = (date(2024, 6, 1), "Indiana Fever", "Connecticut Sun")

    with patch.object(btp, "SessionLocal", return_value=mock_db):
        with patch.object(
            btp,
            "_load_game_keys",
            return_value=[existing_key],
        ):
            with patch.object(
                btp,
                "_existing_keys",
                return_value={existing_key},
            ):
                with patch.object(btp, "_preload_market_lines", return_value={}):
                    mock_ctx = MagicMock()
                    mock_ctx.stats_cache = tsa.TeamStatsCache()
                    with patch.object(btp, "build_context", return_value=mock_ctx):
                        with patch.object(btp, "generate_projection_as_of") as generate:
                            out = btp.run(
                                season_start=date(2024, 5, 1),
                                season_end=date(2024, 12, 31),
                            )

    generate.assert_not_called()
    assert out["status"] == "ok"
    assert out["written"] == 0
    assert out["skipped_existing"] == 1


def test_market_fields_from_projected_over_recommendation():
    fields = btp._market_fields_from_projected(170.0, 165.0)
    assert fields["market_total"] == 165.0
    assert fields["recommendation"] == "OVER"
    assert fields["edge"] == 5.0


def test_sync_market_totals_updates_rows_with_lines():
    mock_db = MagicMock()
    proj = MagicMock()
    proj.game_date = date(2024, 6, 1)
    proj.home_team_name = "Indiana Fever"
    proj.away_team_name = "Connecticut Sun"
    proj.market_total = None
    proj.projected_total = 168.0

    mock_db.query.return_value.filter.return_value.filter.return_value.all.side_effect = [
        [proj],
    ]

    lines = {(date(2024, 6, 1), "Indiana Fever", "Connecticut Sun"): 165.0}

    with patch.object(btp, "SessionLocal", return_value=mock_db):
        with patch.object(btp, "_preload_market_lines", return_value=lines):
            with patch.object(btp, "upsert_many") as upsert:
                out = btp.sync_market_totals_from_lines(
                    season_start=date(2024, 5, 1),
                    season_end=date(2024, 12, 31),
                )

    upsert.assert_called_once()
    batch = upsert.call_args[0][2]
    assert batch[0]["market_total"] == 165.0
    assert batch[0]["edge"] == 3.0
    assert out["updated"] == 1
