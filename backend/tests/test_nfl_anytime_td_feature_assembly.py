"""Tests for nflverse anytime-TD feature assembly (no network)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from app.services.etl.nfl.anytime_td_features import (
    _CONVERSION_RATE_PRIOR,
    _DEF_EPA_PRIOR,
    _PLAYER_RZ_SHARE_PRIOR,
    _RZ_TD_RATE_ALLOWED_PRIOR,
    _TEAM_RZ_PASS_RATE_PRIOR,
    _TEAM_RZ_TRIPS_PRIOR,
    _TDS_ALLOWED_PRIOR,
    _usage_as_of_week_for_priors,
    aggregate_defense_allowed_from_weekly,
    aggregate_player_usage_from_weekly,
    aggregate_team_rz_from_weekly,
    build_player_feature_row,
    build_weekly_feature_rows,
    filter_depth_records_to_latest_snapshot,
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
    # Overall TD/touch is diagnostic only — must not feed λ as conversion_rate.
    assert usage["rb1"]["conversion_rate"] is None
    assert usage["rb1"]["td_per_touch"] is not None
    assert usage["rb1"]["td_per_touch"] < 0.12  # typical overall TD/touch band
    # week 3 row absent — as_of_week=3 excludes week>=3
    usage_w2 = aggregate_player_usage_from_weekly(_weekly_sample(), as_of_week=2)
    assert usage_w2["rb1"]["td_season"] == 1.0


def test_build_player_feature_row_rejects_overall_td_per_touch_as_conversion():
    """Usage TD/touch (~0.05) must not crush RB λ conversion (prior ~0.38)."""
    from app.services.etl.nfl.anytime_td_features import _CONVERSION_RATE_PRIOR

    row = build_player_feature_row(
        player_id="rb1",
        player_name="Star RB",
        position="RB",
        team_name="KC",
        opponent_team_name="BUF",
        season=2026,
        week=1,
        player_stats={
            "player_rz_share": 0.35,
            "conversion_rate": 0.05,  # overall TD/touch — wrong units
            "td_per_touch": 0.05,
        },
    )
    assert row["conversion_rate"] == _CONVERSION_RATE_PRIOR["RB"]
    assert row["td_per_touch"] == 0.05


def test_build_player_feature_row_rb_blends_gl_td_with_prior():
    from app.services.etl.nfl.anytime_td_features import _CONVERSION_RATE_PRIOR

    row = build_player_feature_row(
        player_id="rb1",
        player_name="Star RB",
        position="RB",
        team_name="KC",
        opponent_team_name="BUF",
        season=2026,
        week=1,
        player_stats={
            "player_rz_share": 0.40,
            "conversion_rate": None,
            "gl_td_rate": 0.50,
        },
    )
    prior = _CONVERSION_RATE_PRIOR["RB"]
    expected = 0.45 * prior + 0.55 * 0.50
    assert abs(row["conversion_rate"] - expected) < 1e-9


def test_starting_rb_outranks_featured_te_with_usage_td_per_touch():
    """Regression: board should be RB-led when only overall TD/touch is available."""
    from app.services.etl.nfl.anytime_td_model import (
        RB_TD_DISPERSION,
        anytime_td_probability,
        expected_tds,
    )

    rb = build_player_feature_row(
        player_id="rb1",
        player_name="Starting RB",
        position="RB",
        team_name="MIN",
        opponent_team_name="CHI",
        season=2026,
        week=1,
        player_stats={
            "player_rz_share": 0.32,
            "conversion_rate": 0.045,  # would have crushed λ pre-fix
            "td_per_touch": 0.045,
        },
    )
    te = build_player_feature_row(
        player_id="te1",
        player_name="Featured TE",
        position="TE",
        team_name="MIN",
        opponent_team_name="CHI",
        season=2026,
        week=1,
        player_stats={
            "player_rz_share": 0.18,
            "conversion_rate": 0.11,  # sparse-touch TD/touch near TE floor
            "td_per_touch": 0.11,
        },
    )
    rb_lam = expected_tds(
        team_rz_trips=rb["team_rz_trips"],
        player_rz_share=rb["player_rz_share"],
        conversion_rate=rb["conversion_rate"],
        defense_mult=1.0,
        weather_mult=1.0,
        script_mult=1.0,
    )
    te_lam = expected_tds(
        team_rz_trips=te["team_rz_trips"],
        player_rz_share=te["player_rz_share"],
        conversion_rate=te["conversion_rate"],
        defense_mult=1.0,
        weather_mult=1.0,
        script_mult=1.0,
    )
    rb_p = anytime_td_probability(rb_lam, dispersion=RB_TD_DISPERSION)
    te_p = anytime_td_probability(te_lam, dispersion=None)
    assert rb_p > te_p
    assert rb_p > 0.20  # starting RBs should clear the ~25% TE-board ceiling


def test_aggregate_team_and_defense():
    team = aggregate_team_rz_from_weekly(_weekly_sample(), as_of_week=3)
    assert "KC" in team
    assert team["KC"]["team_rz_trips"] >= 2.0
    defense = aggregate_defense_allowed_from_weekly(_weekly_sample(), as_of_week=3)
    # BUF allowed KC TDs in week 1 (RB 1 + WR 1)
    assert defense["BUF"]["RB"] >= 0
    assert defense["BUF"]["WR"] >= 0


def test_build_player_feature_row_tolerates_none_numeric_fields():
    """Week-1 / missing-defense path sets explicit None values; must not float(None)."""
    row = build_player_feature_row(
        player_id="00-0036139",
        player_name="Rico Dowdle",
        position="RB",
        team_name="PIT",
        opponent_team_name="NYJ",
        season=2026,
        week=1,
        player_stats={
            "player_rz_share": None,
            "conversion_rate": None,
            "snap_pct": None,
            "availability_mult": None,
            "gl_td_rate": None,
            "rz_rush_share": None,
            "gl_carry_share": None,
        },
        team_stats={
            "team_rz_trips": None,
            "team_rz_pass_rate": None,
            "early_down_pass_pct": None,
        },
        # Mirrors build_weekly_feature_rows when defense.get(opp) is {}.
        opponent_defense={
            "tds_allowed_vs_pos": None,
            "rz_td_rate_allowed": None,
            "def_epa": None,
        },
        weather={"outdoor": True, "wind_mph": None, "precip": False},
        game_env={
            "implied_team_total": None,
            "implied_total": None,
            "spread": None,
        },
    )
    assert row["team_name"] == "Pittsburgh Steelers"
    assert row["team_rz_trips"] == _TEAM_RZ_TRIPS_PRIOR
    assert row["player_rz_share"] == _PLAYER_RZ_SHARE_PRIOR["RB"]
    assert row["conversion_rate"] == _CONVERSION_RATE_PRIOR["RB"]
    assert row["tds_allowed_vs_pos"] == _TDS_ALLOWED_PRIOR["RB"]
    assert row["rz_td_rate_allowed"] == _RZ_TD_RATE_ALLOWED_PRIOR
    assert row["def_epa"] == _DEF_EPA_PRIOR
    assert row["team_rz_pass_rate"] == _TEAM_RZ_PASS_RATE_PRIOR
    assert row["availability_mult"] == 1.0
    assert row["wind_mph"] is None
    assert row["implied_total"] is None
    assert row["spread"] is None
    assert isinstance(row["defense_mult"], float)
    assert isinstance(row["script_mult"], float)


def test_build_weekly_feature_rows_week1_with_empty_defense_stats():
    """End-to-end assembly must not crash when opponent has no prior defense rows."""
    weekly = _weekly_sample()
    depth = [
        {
            "gsis_id": "rb1",
            "full_name": "Star RB",
            "position": "RB",
            "club_code": "KC",
            "depth_team": 1,
            "depth_position": "RB",
            "week": 1,
            "dt": "2026-09-01",
        },
        {
            "gsis_id": "wr1",
            "full_name": "Star WR",
            "position": "WR",
            "club_code": "KC",
            "depth_team": 1,
            "depth_position": "WR",
            "week": 1,
            "dt": "2026-09-01",
        },
    ]
    schedules = [
        {
            "week": 1,
            "game_type": "REG",
            "home_team": "KC",
            "away_team": "BUF",
            "gameday": "2026-09-07",
            "roof": "outdoors",
            "temp": None,
            "wind": None,
        }
    ]
    # as_of_week=1 ⇒ no prior weeks ⇒ empty defense / team_rz for everyone.
    rows = build_weekly_feature_rows(
        2026,
        1,
        weekly_records=weekly,
        schedule_records=schedules,
        depth_records=depth,
        usage_as_of_week=1,
        pbp_as_of_week=1,
    )
    assert rows
    assert all(isinstance(r["rz_td_rate_allowed"], float) for r in rows)
    assert all(r["team_name"] for r in rows)


def test_select_universe_includes_rb2_excludes_st_and_deep_backups():
    depth = [
        {
            "gsis_id": "rb1",
            "full_name": "Star RB",
            "position": "RB",
            "club_code": "KC",
            "depth_team": 1,
            "depth_position": "RB",
            "week": 3,
        },
        {
            "gsis_id": "rb2",
            "full_name": "Backup RB",
            "position": "RB",
            "club_code": "KC",
            "depth_team": 2,
            "depth_position": "RB",
            "week": 3,
        },
        {
            "gsis_id": "rb3",
            "full_name": "Third RB",
            "position": "RB",
            "club_code": "KC",
            "depth_team": 3,
            "depth_position": "RB",
            "week": 3,
        },
        {
            "gsis_id": "qb1",
            "full_name": "QB One",
            "position": "QB",
            "club_code": "KC",
            "depth_team": 1,
            "depth_position": "QB",
            "week": 3,
        },
        {
            "gsis_id": "qb2",
            "full_name": "Backup QB",
            "position": "QB",
            "club_code": "KC",
            "depth_team": 2,
            "depth_position": "QB",
            "week": 3,
        },
        {
            "gsis_id": "wr_kr",
            "full_name": "Return WR",
            "position": "WR",
            "club_code": "KC",
            "depth_team": 1,
            "depth_position": "KR",
            "week": 3,
        },
        {
            "gsis_id": "wr1",
            "full_name": "Star WR",
            "position": "WR",
            "club_code": "KC",
            "depth_team": 1,
            "depth_position": "WR",
            "week": 3,
        },
    ]
    usage = aggregate_player_usage_from_weekly(_weekly_sample(), as_of_week=3)
    universe = select_skill_universe(depth_records=depth, usage_by_player=usage, week=3)
    ids = {p["player_id"] for p in universe}
    assert "rb1" in ids
    assert "rb2" in ids  # RB2 on board with depth club
    assert "qb1" in ids
    assert "wr1" in ids
    assert "rb3" not in ids  # beyond RB depth cap
    assert "qb2" not in ids  # QB backups stay off the board
    assert "wr_kr" not in ids  # special teams depth_position


def test_select_universe_fills_wr_and_rb_slots_from_usage():
    depth = [
        {
            "gsis_id": "qb1",
            "full_name": "QB One",
            "position": "QB",
            "club_code": "KC",
            "depth_team": 1,
            "depth_position": "QB",
            "week": 3,
        },
        {
            "gsis_id": "rb1",
            "full_name": "Star RB",
            "position": "RB",
            "club_code": "KC",
            "depth_team": 1,
            "depth_position": "RB",
            "week": 3,
        },
        {
            "gsis_id": "wr1",
            "full_name": "Star WR",
            "position": "WR",
            "club_code": "KC",
            "depth_team": 1,
            "depth_position": "WR",
            "week": 3,
        },
    ]
    usage = aggregate_player_usage_from_weekly(_weekly_sample(), as_of_week=3)
    usage["wr2"] = {
        "player_id": "wr2",
        "player_name": "WR Two",
        "position": "WR",
        "team_abbr": "KC",
        "touches_season": 20.0,
        "targets_l3": 18.0,
        "carries_l3": 0.0,
    }
    usage["rb_committee"] = {
        "player_id": "rb_committee",
        "player_name": "RB Two",
        "position": "RB",
        "team_abbr": "KC",
        "touches_season": 25.0,
        "targets_l3": 4.0,
        "carries_l3": 12.0,
    }
    universe = select_skill_universe(depth_records=depth, usage_by_player=usage, week=3)
    ids = {p["player_id"] for p in universe}
    assert "wr1" in ids
    assert "wr2" in ids
    assert "rb1" in ids
    assert "rb_committee" in ids


def test_select_universe_usage_fallback_when_no_depth():
    usage = aggregate_player_usage_from_weekly(_weekly_sample(), as_of_week=3)
    universe = select_skill_universe(depth_records=[], usage_by_player=usage, week=3)
    ids = {p["player_id"] for p in universe}
    # Top usage starters only (no depth) — rb1/wr1 qualify; buf_rb may too.
    assert "rb1" in ids
    assert "wr1" in ids


def test_select_universe_prefers_depth_team_over_stale_usage():
    """Depth club_code wins when prior-week usage still has the old team."""
    depth = [
        {
            "gsis_id": "dowdle",
            "full_name": "Rico Dowdle",
            "position": "RB",
            "club_code": "CAR",
            "depth_team": 1,
            "depth_position": "RB",
            "week": 1,
        },
        {
            "gsis_id": "mason",
            "full_name": "Jordan Mason",
            "position": "RB",
            "club_code": "MIN",
            "depth_team": 1,
            "depth_position": "RB",
            "week": 1,
        },
    ]
    usage = {
        "dowdle": {
            "player_id": "dowdle",
            "player_name": "Rico Dowdle",
            "position": "RB",
            "team_abbr": "DAL",  # stale prior-team from weekly
            "touches_season": 120.0,
            "targets_l3": 4.0,
            "carries_l3": 50.0,
        },
        "mason": {
            "player_id": "mason",
            "player_name": "Jordan Mason",
            "position": "RB",
            "team_abbr": "SF",  # stale prior-team from weekly
            "touches_season": 90.0,
            "targets_l3": 2.0,
            "carries_l3": 40.0,
        },
    }
    universe = select_skill_universe(depth_records=depth, usage_by_player=usage, week=1)
    by_id = {p["player_id"]: p for p in universe}
    assert by_id["dowdle"]["team_abbr"] == "CAR"
    assert by_id["mason"]["team_abbr"] == "MIN"
    # Usage may still enrich the display name.
    assert by_id["dowdle"]["player_name"] == "Rico Dowdle"


def test_select_universe_includes_rb2_with_depth_club_over_stale_usage():
    """PIT RB2 Dowdle enters the slate as PIT even when usage still says CAR."""
    depth = [
        {
            "gsis_id": "warren",
            "full_name": "Jaylen Warren",
            "position": "RB",
            "club_code": "PIT",
            "depth_team": 1,
            "depth_position": "RB",
            "week": 1,
        },
        {
            "gsis_id": "dowdle",
            "full_name": "Rico Dowdle",
            "position": "RB",
            "club_code": "PIT",
            "depth_team": 2,
            "depth_position": "RB",
            "week": 1,
        },
        {
            "gsis_id": "dowdle",
            "full_name": "Rico Dowdle",
            "position": "RB",
            "club_code": "PIT",
            "depth_team": 1,
            "depth_position": "KR",
            "week": 1,
        },
        {
            "gsis_id": "rodgers",
            "full_name": "Aaron Rodgers",
            "position": "QB",
            "club_code": "PIT",
            "depth_team": 1,
            "depth_position": "QB",
            "week": 1,
        },
    ]
    usage = {
        "dowdle": {
            "player_id": "dowdle",
            "player_name": "Rico Dowdle",
            "position": "RB",
            "team_abbr": "CAR",  # stale prior club from weekly fallback
            "touches_season": 200.0,
            "targets_l3": 6.0,
            "carries_l3": 80.0,
        },
        "warren": {
            "player_id": "warren",
            "player_name": "Jaylen Warren",
            "position": "RB",
            "team_abbr": "PIT",
            "touches_season": 150.0,
            "targets_l3": 8.0,
            "carries_l3": 60.0,
        },
    }
    universe = select_skill_universe(depth_records=depth, usage_by_player=usage, week=1)
    by_id = {p["player_id"]: p for p in universe}
    assert "dowdle" in by_id
    assert by_id["dowdle"]["team_abbr"] == "PIT"
    assert by_id["dowdle"]["depth_team"] == 2
    assert by_id["warren"]["team_abbr"] == "PIT"


def test_usage_fill_assigns_depth_team_by_slot():
    """Usage-filled RB2 gets depth_team=2 (backup λ priors), not starter=1."""
    depth = [
        {
            "gsis_id": "rb1",
            "full_name": "Star RB",
            "position": "RB",
            "club_code": "BAL",
            "depth_team": 1,
            "depth_position": "RB",
            "week": 1,
        },
        {
            "gsis_id": "qb1",
            "full_name": "QB One",
            "position": "QB",
            "club_code": "BAL",
            "depth_team": 1,
            "depth_position": "QB",
            "week": 1,
        },
    ]
    usage = {
        "hill": {
            "player_id": "hill",
            "player_name": "Justice Hill",
            "position": "RB",
            "team_abbr": "BAL",
            "touches_season": 50.0,
            "targets_l3": 2.0,
            "carries_l3": 25.0,
        },
    }
    universe = select_skill_universe(depth_records=depth, usage_by_player=usage, week=1)
    by_id = {p["player_id"]: p for p in universe}
    assert by_id["hill"]["depth_team"] == 2
    assert by_id["rb1"]["depth_team"] == 1


def test_rb1_outranks_rb2_under_depth_priors():
    """Hierarchical-only: starting RB clearly above backup when shares missing."""
    from app.services.etl.nfl.anytime_td_model import (
        RB_TD_DISPERSION,
        anytime_td_probability,
        expected_tds,
    )

    rb1 = build_player_feature_row(
        player_id="henry",
        player_name="Derrick Henry",
        position="RB",
        team_name="BAL",
        opponent_team_name="BUF",
        season=2026,
        week=1,
        depth_team=1,
        player_stats={"player_rz_share": None, "conversion_rate": None},
    )
    rb2 = build_player_feature_row(
        player_id="hill",
        player_name="Justice Hill",
        position="RB",
        team_name="BAL",
        opponent_team_name="BUF",
        season=2026,
        week=1,
        depth_team=2,
        player_stats={"player_rz_share": None, "conversion_rate": None},
    )
    assert rb1["player_rz_share"] > rb2["player_rz_share"]
    assert rb1["conversion_rate"] > rb2["conversion_rate"]
    p1 = anytime_td_probability(
        expected_tds(
            team_rz_trips=rb1["team_rz_trips"],
            player_rz_share=rb1["player_rz_share"],
            conversion_rate=rb1["conversion_rate"],
            defense_mult=1.0,
            weather_mult=1.0,
            script_mult=1.0,
        ),
        dispersion=RB_TD_DISPERSION,
    )
    p2 = anytime_td_probability(
        expected_tds(
            team_rz_trips=rb2["team_rz_trips"],
            player_rz_share=rb2["player_rz_share"],
            conversion_rate=rb2["conversion_rate"],
            defense_mult=1.0,
            weather_mult=1.0,
            script_mult=1.0,
        ),
        dispersion=RB_TD_DISPERSION,
    )
    assert p1 > p2 + 0.08  # clear separation (not ~30% twin)
    assert p1 > 0.22
    assert p2 < 0.18


def test_backup_pbp_share_soft_capped_vs_starter():
    """Even with starter-like PBP rush share, RB2 cannot match RB1 λ."""
    from app.services.etl.nfl.anytime_td_model import (
        RB_TD_DISPERSION,
        anytime_td_probability,
        expected_tds,
    )

    starter = build_player_feature_row(
        player_id="gibbs",
        player_name="Jahmyr Gibbs",
        position="RB",
        team_name="DET",
        opponent_team_name="GB",
        season=2026,
        week=1,
        depth_team=1,
        player_stats={"rz_rush_share": 0.45, "gl_carry_share": 0.50},
    )
    backup = build_player_feature_row(
        player_id="vaki",
        player_name="Sione Vaki",
        position="RB",
        team_name="DET",
        opponent_team_name="GB",
        season=2026,
        week=1,
        depth_team=2,
        player_stats={"rz_rush_share": 0.45, "gl_carry_share": 0.50},
    )
    assert starter["player_rz_share"] > backup["player_rz_share"]
    p_s = anytime_td_probability(
        expected_tds(
            team_rz_trips=3.2,
            player_rz_share=starter["player_rz_share"],
            conversion_rate=starter["conversion_rate"],
            defense_mult=1.0,
            weather_mult=1.0,
            script_mult=1.0,
        ),
        dispersion=RB_TD_DISPERSION,
    )
    p_b = anytime_td_probability(
        expected_tds(
            team_rz_trips=3.2,
            player_rz_share=backup["player_rz_share"],
            conversion_rate=backup["conversion_rate"],
            defense_mult=1.0,
            weather_mult=1.0,
            script_mult=1.0,
        ),
        dispersion=RB_TD_DISPERSION,
    )
    assert p_s > p_b


def test_usage_fill_remaps_team_via_depth_club_within_cap():
    """Within-cap depth club wins over stale usage recent_team (RB2 on board)."""
    depth = [
        {
            "gsis_id": "rb1",
            "full_name": "Star RB",
            "position": "RB",
            "club_code": "PIT",
            "depth_team": 1,
            "depth_position": "RB",
            "week": 1,
        },
        {
            "gsis_id": "qb1",
            "full_name": "QB One",
            "position": "QB",
            "club_code": "PIT",
            "depth_team": 1,
            "depth_position": "QB",
            "week": 1,
        },
        # Within-cap depth on PIT while usage still says CAR → depth club wins.
        {
            "gsis_id": "rb_fill",
            "full_name": "Usage RB",
            "position": "RB",
            "club_code": "PIT",
            "depth_team": 2,
            "depth_position": "RB",
            "week": 1,
        },
    ]
    usage = {
        "rb_fill": {
            "player_id": "rb_fill",
            "player_name": "Usage RB",
            "position": "RB",
            "team_abbr": "CAR",
            "touches_season": 80.0,
            "targets_l3": 2.0,
            "carries_l3": 40.0,
        },
    }
    universe = select_skill_universe(depth_records=depth, usage_by_player=usage, week=1)
    by_id = {p["player_id"]: p for p in universe}
    assert by_id["rb_fill"]["team_abbr"] == "PIT"
    assert by_id["rb_fill"]["depth_team"] == 2


def test_usage_fill_ignores_out_of_cap_depth_club():
    """Deep depth slots on a wrong club must not pull a usage player onto that team."""
    depth = [
        {
            "gsis_id": "rb1",
            "full_name": "Star RB",
            "position": "RB",
            "club_code": "LAC",
            "depth_team": 1,
            "depth_position": "RB",
            "week": 1,
        },
        {
            "gsis_id": "qb1",
            "full_name": "QB One",
            "position": "QB",
            "club_code": "LAC",
            "depth_team": 1,
            "depth_position": "QB",
            "week": 1,
        },
        {
            "gsis_id": "qb_bal",
            "full_name": "BAL QB",
            "position": "QB",
            "club_code": "BAL",
            "depth_team": 1,
            "depth_position": "QB",
            "week": 1,
        },
        {
            "gsis_id": "rb_bal",
            "full_name": "BAL RB1",
            "position": "RB",
            "club_code": "BAL",
            "depth_team": 1,
            "depth_position": "RB",
            "week": 1,
        },
        # Stale RB3 on LAC for a BAL player — must not remap Mitchell→LAC.
        {
            "gsis_id": "mitchell",
            "full_name": "Keaton Mitchell",
            "position": "RB",
            "club_code": "LAC",
            "depth_team": 3,
            "depth_position": "RB",
            "week": 1,
        },
    ]
    usage = {
        "mitchell": {
            "player_id": "mitchell",
            "player_name": "Keaton Mitchell",
            "position": "RB",
            "team_abbr": "BAL",
            "touches_season": 40.0,
            "targets_l3": 1.0,
            "carries_l3": 20.0,
        },
    }
    universe = select_skill_universe(depth_records=depth, usage_by_player=usage, week=1)
    by_id = {p["player_id"]: p for p in universe}
    assert "mitchell" in by_id
    assert by_id["mitchell"]["team_abbr"] == "BAL"
    assert by_id["mitchell"]["depth_team"] == 2  # usage-filled as BAL RB2


def test_filter_depth_records_keeps_latest_dt_snapshot_only():
    depth = [
        {
            "gsis_id": "rb1",
            "full_name": "Old Snap RB",
            "position": "RB",
            "club_code": "DAL",
            "depth_team": 1,
            "depth_position": "RB",
            "week": 1,
            "dt": "2024-08-01",
        },
        {
            "gsis_id": "rb1",
            "full_name": "New Snap RB",
            "position": "RB",
            "club_code": "CAR",
            "depth_team": 1,
            "depth_position": "RB",
            "week": 1,
            "dt": "2025-09-01",
        },
    ]
    filtered = filter_depth_records_to_latest_snapshot(depth)
    assert len(filtered) == 1
    assert filtered[0]["club_code"] == "CAR"

    usage = {
        "rb1": {
            "player_id": "rb1",
            "player_name": "Rico Dowdle",
            "position": "RB",
            "team_abbr": "DAL",
            "touches_season": 100.0,
            "targets_l3": 3.0,
            "carries_l3": 40.0,
        }
    }
    universe = select_skill_universe(depth_records=depth, usage_by_player=usage, week=1)
    assert len(universe) == 1
    assert universe[0]["team_abbr"] == "CAR"


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
