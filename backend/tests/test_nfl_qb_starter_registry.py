"""Tests for QB depth chart snapshot filtering and starter overrides."""

from __future__ import annotations

import pandas as pd

from app.services.etl.nfl.qb_dynamic import get_dynamic_starting_qbs
from app.services.etl.nfl.qb_starter_registry import (
    filter_depth_charts_to_latest_snapshot,
    get_starter_override,
    resolve_qb_starter_for_team,
)


def _sample_2025_format_depth() -> pd.DataFrame:
    """Two snapshots: stale ATL/MIA starters vs latest curated-correct ranks."""
    return pd.DataFrame(
        [
            {
                "dt": "2026-08-01T00:00:00Z",
                "team": "ATL",
                "player_name": "Tua Tagovailoa",
                "gsis_id": "00-0036212",
                "pos_abb": "QB",
                "pos_rank": 1,
            },
            {
                "dt": "2026-08-01T00:00:00Z",
                "team": "ATL",
                "player_name": "Michael Penix Jr.",
                "gsis_id": "00-0039917",
                "pos_abb": "QB",
                "pos_rank": 2,
            },
            {
                "dt": "2026-08-01T00:00:00Z",
                "team": "MIA",
                "player_name": "Malik Willis",
                "gsis_id": "00-0038128",
                "pos_abb": "QB",
                "pos_rank": 1,
            },
            {
                "dt": "2026-08-12T00:00:00Z",
                "team": "ATL",
                "player_name": "Tua Tagovailoa",
                "gsis_id": "00-0036212",
                "pos_abb": "QB",
                "pos_rank": 1,
            },
            {
                "dt": "2026-08-12T00:00:00Z",
                "team": "ATL",
                "player_name": "Michael Penix Jr.",
                "gsis_id": "00-0039917",
                "pos_abb": "QB",
                "pos_rank": 2,
            },
            {
                "dt": "2026-08-12T00:00:00Z",
                "team": "MIA",
                "player_name": "Malik Willis",
                "gsis_id": "00-0038128",
                "pos_abb": "QB",
                "pos_rank": 1,
            },
            {
                "dt": "2026-08-12T00:00:00Z",
                "team": "MIA",
                "player_name": "Quinn Ewers",
                "gsis_id": "00-0049999",
                "pos_abb": "QB",
                "pos_rank": 2,
            },
            {
                "dt": "2026-08-12T00:00:00Z",
                "team": "NE",
                "player_name": "Drake Maye",
                "gsis_id": "00-0039337",
                "pos_abb": "QB",
                "pos_rank": 1,
            },
        ]
    )


def test_filter_depth_charts_to_latest_snapshot():
    raw = _sample_2025_format_depth()
    filtered = filter_depth_charts_to_latest_snapshot(raw)
    assert set(filtered["dt"].unique()) == {"2026-08-12T00:00:00Z"}
    assert len(filtered) == 5


def test_resolve_override_penix_on_atl():
    qb_depth = filter_depth_charts_to_latest_snapshot(_sample_2025_format_depth())
    team_qbs = qb_depth[qb_depth["team"] == "ATL"]
    row = resolve_qb_starter_for_team(
        team="ATL",
        team_qbs=team_qbs,
        full_qb_depth=qb_depth,
        override_name=get_starter_override(2026, "ATL"),
        use_2025_format=True,
    )
    assert row is not None
    assert row["player_name"] == "Michael Penix Jr."


def test_resolve_override_tua_on_mia_from_global_lookup():
    qb_depth = filter_depth_charts_to_latest_snapshot(_sample_2025_format_depth())
    team_qbs = qb_depth[qb_depth["team"] == "MIA"]
    row = resolve_qb_starter_for_team(
        team="MIA",
        team_qbs=team_qbs,
        full_qb_depth=qb_depth,
        override_name=get_starter_override(2026, "MIA"),
        use_2025_format=True,
    )
    assert row is not None
    assert row["player_name"] == "Tua Tagovailoa"
    assert row["gsis_id"] == "00-0036212"


def test_get_dynamic_starting_qbs_applies_overrides(monkeypatch):
    depth = _sample_2025_format_depth()

    def fake_import_depth_charts(seasons):
        return depth

    def fake_import_injuries(seasons):
        return pd.DataFrame()

    monkeypatch.setattr(
        "app.services.etl.nfl.qb_dynamic.nfl.import_depth_charts",
        fake_import_depth_charts,
    )
    monkeypatch.setattr(
        "app.services.etl.nfl.qb_dynamic.nfl.import_injuries",
        fake_import_injuries,
    )
    monkeypatch.setattr(
        "app.services.etl.nfl.qb_dynamic.get_game_kickoff",
        lambda team, season, week: None,
    )

    qbs = get_dynamic_starting_qbs(2026, 1)
    by_team = {q["team_abbr"]: q for q in qbs}

    assert by_team["ATL"]["name"] == "Michael Penix Jr."
    assert by_team["ATL"]["team_name"] == "Atlanta Falcons"
    assert by_team["MIA"]["name"] == "Tua Tagovailoa"
    assert by_team["MIA"]["team_name"] == "Miami Dolphins"
    assert by_team["NE"]["name"] == "Drake Maye"
