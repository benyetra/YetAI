"""NFL projection fixes: current-season nflverse data, the shrunk QB tier,
frozen kicked-off rows, name matching and the implied team total."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from app.services.etl.nfl import nfl_common, qb_betting, qb_dynamic
from app.services.etl.nfl.nflverse_weekly import (
    load_weekly_frame,
    normalize_weekly_frame,
    weekly_qb_records,
)
from app.services.etl.nfl.player_names import find_by_player_name, player_name_key
from app.services.etl.nfl.qb_features import (
    MIN_FORM_ATTEMPTS,
    TIER_PRIOR_GAMES,
    blend_tier_with_form,
    dynamic_tier_from_history,
    estimate_opp_pass_allowed_from_weekly,
    implied_team_total_from_expected_margin,
    implied_team_total_from_market,
    league_pass_allowed_from_weekly,
    opponent_pass_factor,
    prior_game_stats_for_player,
    prior_yards_for_player,
)

# ---- nflverse weekly loader ------------------------------------------------


def _new_release_frame():
    return pd.DataFrame(
        [
            {
                "player_id": "00-1",
                "player_display_name": "Josh Allen",
                "position": "QB",
                "season": 2026,
                "week": 3,
                "season_type": "REG",
                "team": "BUF",
                "opponent_team": "MIA",
                "attempts": 34,
                "completions": 22,
                "passing_yards": 281,
                "sacks_suffered": 2,
                "passing_air_yards": 290,
                "passing_epa": 5.1,
            },
            {
                "player_id": "00-2",
                "player_display_name": "Gadget Guy",
                "position": "QB",
                "season": 2026,
                "week": 3,
                "season_type": "REG",
                "team": "BUF",
                "opponent_team": "MIA",
                "attempts": 0,
                "completions": 0,
                "passing_yards": 0,
                "sacks_suffered": 0,
            },
            {
                "player_id": "00-1",
                "player_display_name": "Josh Allen",
                "position": "QB",
                "season": 2026,
                "week": 19,
                "season_type": "POST",
                "team": "BUF",
                "opponent_team": "KC",
                "attempts": 40,
                "completions": 25,
                "passing_yards": 300,
                "sacks_suffered": 1,
            },
        ]
    )


def test_loader_falls_back_to_the_new_release_when_legacy_file_is_gone():
    def legacy(_season):
        raise RuntimeError("HTTP Error 404: Not Found")

    frame = load_weekly_frame(
        2026, legacy_reader=legacy, release_reader=lambda _s: _new_release_frame()
    )
    assert frame is not None
    assert list(frame["recent_team"]) == ["BUF", "BUF", "BUF"]
    assert list(frame["sacks"]) == [2, 0, 1]


def test_loader_returns_none_when_neither_source_has_the_season():
    def missing(_season):
        raise RuntimeError("404")

    assert (
        load_weekly_frame(2030, legacy_reader=missing, release_reader=missing) is None
    )


def test_normalize_keeps_legacy_columns_untouched():
    legacy = pd.DataFrame([{"recent_team": "BUF", "team": "XXX", "sacks": 3}])
    assert normalize_weekly_frame(legacy).iloc[0]["recent_team"] == "BUF"


def test_weekly_qb_records_keep_reg_passers_only():
    records = weekly_qb_records(normalize_weekly_frame(_new_release_frame()))
    assert len(records) == 1  # no zero-attempt row, no playoff row
    rec = records[0]
    assert rec["recent_team"] == "BUF"
    assert rec["sacks"] == 2.0
    assert rec["attempts"] == 34.0
    assert rec["actual_passing_yards"] == 281.0


def test_qb_history_loads_last_season_and_this_one():
    frames = {
        2025: _new_release_frame().assign(season=2025),
        2026: _new_release_frame(),
    }
    with patch(
        "app.services.etl.nfl.nflverse_weekly.load_weekly_frame",
        side_effect=lambda season: normalize_weekly_frame(frames[season]),
    ):
        history = qb_dynamic._load_weekly_qb_history(2026)
    assert sorted(r["season"] for r in history) == [2025, 2026]


# ---- dynamic tier ------------------------------------------------------------


def _starts(*yards, season=2026):
    return [{"yards": y, "season": season, "attempts": 34.0} for y in yards]


def test_dynamic_tier_is_the_table_with_no_starts():
    assert dynamic_tier_from_history(250.0, [], season=2026) == 250.0


def test_dynamic_tier_moves_toward_what_the_qb_actually_throws():
    one = dynamic_tier_from_history(250.0, _starts(150), season=2026)
    many = dynamic_tier_from_history(250.0, _starts(*[150] * 9), season=2026)
    assert one == round((TIER_PRIOR_GAMES * 250 + 150) / (TIER_PRIOR_GAMES + 1), 1)
    assert 150.0 < many < one < 250.0
    # The legacy blend ignored fewer than three games entirely.
    assert blend_tier_with_form(250.0, [150.0]) == 250.0


def test_dynamic_tier_counts_last_season_less_and_older_seasons_not_at_all():
    this_year = dynamic_tier_from_history(250.0, _starts(150, 150), season=2026)
    last_year = dynamic_tier_from_history(
        250.0, _starts(150, 150, season=2025), season=2026
    )
    ancient = dynamic_tier_from_history(
        250.0, _starts(150, 150, season=2023), season=2026
    )
    assert this_year < last_year < 250.0
    assert ancient == 250.0


def test_dynamic_tier_rescues_a_qb_missing_from_the_name_table():
    # Unknown names get the 210 default; a QB averaging 290 should not stay there.
    assert dynamic_tier_from_history(210.0, _starts(*[290] * 8), season=2026) > 255.0


def test_dynamic_tier_applies_opponent_factor_and_clamps():
    base = dynamic_tier_from_history(250.0, [], season=2026)
    soft = dynamic_tier_from_history(250.0, [], season=2026, opp_factor=1.05)
    assert soft == round(base * 1.05, 1)
    assert dynamic_tier_from_history(900.0, [], season=2026) == 350.0
    assert dynamic_tier_from_history(10.0, [], season=2026) == 120.0


def test_opponent_pass_factor_is_a_quarter_of_the_gap_and_bounded():
    assert opponent_pass_factor(None, 220.0) == 1.0
    assert opponent_pass_factor(264.0, 220.0) == 1.05  # +20% allowed -> +5%
    assert opponent_pass_factor(1000.0, 220.0) == 1.1
    assert opponent_pass_factor(10.0, 220.0) == 0.9


def _qb_row(week, yards, attempts, *, pid="00-1", team="BUF", opp="MIA", season=2026):
    return {
        "qb_player_id": pid,
        "qb_player_name": "Some Qb",
        "season": season,
        "week": week,
        "actual_passing_yards": yards,
        "passing_yards": yards,
        "attempts": attempts,
        "recent_team": team,
        "opponent_team": opp,
        "position": "QB",
    }


def test_relief_cameos_are_not_form():
    history = [_qb_row(1, 260, 35), _qb_row(2, 12, 3), _qb_row(3, 240, 31)]
    kwargs = dict(player_key="00-1", season=2026, week=4)
    assert prior_yards_for_player(history, **kwargs) == [260, 12, 240]
    assert prior_yards_for_player(
        history, min_attempts=MIN_FORM_ATTEMPTS, **kwargs
    ) == [260, 240]
    stats = prior_game_stats_for_player(
        history, min_attempts=MIN_FORM_ATTEMPTS, **kwargs
    )
    assert [s["yards"] for s in stats] == [260, 240]
    assert [s["season"] for s in stats] == [2026.0, 2026.0]


def test_rows_without_attempts_are_kept_by_the_cameo_filter():
    history = [{k: v for k, v in _qb_row(1, 260, 35).items() if k != "attempts"}]
    assert prior_yards_for_player(
        history,
        player_key="00-1",
        season=2026,
        week=2,
        min_attempts=MIN_FORM_ATTEMPTS,
    ) == [260]


def test_opponent_pass_allowed_sums_every_passer_in_a_game():
    history = [
        _qb_row(1, 200, 28, pid="a", team="BUF", opp="KC"),
        _qb_row(1, 40, 6, pid="b", team="BUF", opp="KC"),  # relief QB, same game
        _qb_row(2, 260, 36, pid="c", team="LAC", opp="KC"),
        _qb_row(2, 180, 30, pid="d", team="DEN", opp="LV"),
    ]
    allowed = estimate_opp_pass_allowed_from_weekly(
        history, opponent_abbr="KC", season=2026, week=4
    )
    assert allowed == (240 + 260) / 2  # not (200 + 40 + 260) / 3
    assert (
        estimate_opp_pass_allowed_from_weekly(
            history, opponent_abbr="KC", season=2026, week=4, min_games=3
        )
        is None
    )
    assert (
        league_pass_allowed_from_weekly(history, season=2026, week=4)
        == (240 + 260 + 180) / 3
    )


def test_context_publishes_the_shrunk_tier_and_ignores_cameos():
    history = [_qb_row(w, 300, 36) for w in range(1, 6)] + [_qb_row(6, 9, 2)]
    with (
        patch.object(qb_dynamic, "_implied_team_total_for_team", return_value=None),
        patch.object(qb_dynamic, "_market_lines_for_team", return_value={}),
        patch.object(qb_dynamic, "team_is_home", return_value=1.0),
    ):
        ctx = qb_dynamic.build_qb_prediction_context(
            qb_name="Some Qb",
            player_id="00-1",
            team_abbr="BUF",
            opponent_abbr="NYJ",
            season=2026,
            week=7,
            weekly_history=history,
            static_tier_yards=240.0,
        )
    assert ctx["prior_starts"] == 5
    assert ctx["rolling_yards_l3"] == 300.0
    assert ctx["dynamic_tier_yards"] == round((4 * 240 + 5 * 300) / 9, 1)


# ---- implied team total ---------------------------------------------------------


def test_implied_total_from_nflverse_margin_gives_the_favorite_more():
    # nflverse: +6.5 means this team is favored by 6.5.
    favorite = implied_team_total_from_expected_margin(total_line=47.5, team_margin=6.5)
    underdog = implied_team_total_from_expected_margin(
        total_line=47.5, team_margin=-6.5
    )
    assert favorite == 27.0 and underdog == 20.5
    # Sportsbook convention (negative = favored) agrees.
    assert implied_team_total_from_market(total_line=47.5, spread_line=-6.5) == 27.0


def test_schedule_market_lines_give_the_home_favorite_the_bigger_total():
    game = pd.Series(
        {
            "home_team": "BUF",
            "away_team": "NYJ",
            "total_line": 47.5,
            "spread_line": 6.5,  # home favored by 6.5
            "roof": "outdoors",
        }
    )
    with patch.object(qb_dynamic, "_team_game_row", return_value=game):
        home = qb_dynamic._market_lines_for_team("BUF", 2026, 10)
        away = qb_dynamic._market_lines_for_team("NYJ", 2026, 10)
    assert home["implied_team_total"] == 27.0
    assert away["implied_team_total"] == 20.5


# ---- frozen once kicked off ------------------------------------------------------


def test_has_kicked_off():
    now = datetime(2026, 11, 10, 4, 30)  # Tuesday morning run
    assert nfl_common.has_kicked_off(datetime(2026, 11, 8, 13, 0), now=now)
    assert not nfl_common.has_kicked_off(datetime(2026, 11, 15, 13, 0), now=now)
    assert not nfl_common.has_kicked_off(None, now=now)
    assert nfl_common.has_kicked_off(date(2026, 11, 9), now=now)
    assert not nfl_common.has_kicked_off(date(2026, 11, 10), now=now)


def test_week_helper_still_points_at_the_played_week_until_thursday():
    # Why rows must be frozen: Tuesday of Week 10 still resolves to Week 9.
    assert nfl_common.get_current_nfl_week(2026, today=date(2026, 11, 10)) == 9
    assert nfl_common.get_current_nfl_week(2026, today=date(2026, 11, 12)) == 10


def test_qb_betting_does_not_attach_next_weeks_line_to_a_played_game(monkeypatch):
    played = SimpleNamespace(
        qb_player_name="Josh Allen",
        game_date=datetime(2026, 11, 8, 13, 0),
        ou_line=262.5,
        predicted_passing_yards=265.0,
        betting_recommendation="PASS",
        feature_importance={},
        model_confidence=0.8,
        prediction_interval_lower=230.0,
        prediction_interval_upper=300.0,
        prediction_method="soft_anchor",
    )
    session = MagicMock()
    query = session.query.return_value
    query.filter_by.return_value.limit.return_value.all.return_value = [played]
    query.filter.return_value.all.return_value = []
    monkeypatch.setattr(qb_betting, "db_session", session)
    monkeypatch.setattr(
        qb_betting,
        "get_nfl_games_and_lines",
        lambda: {
            "Josh Allen": {
                "FanDuel": {
                    "over": {"line": 241.5, "odds": -110},
                    "under": {"line": 241.5, "odds": -110},
                }
            }
        },
    )
    monkeypatch.setattr(
        qb_betting, "has_kicked_off", lambda kickoff: kickoff < datetime(2026, 11, 10)
    )

    qb_betting._run_qb_betting_core()

    assert played.ou_line == 262.5  # the closing line it is graded against
    assert played.predicted_passing_yards == 265.0
    session.commit.assert_not_called()


def test_qb_lines_match_on_name_key_not_substring():
    lines = {"CJ Stroud": {"book": 1}, "Josh Allen Jr": {"book": 2}}
    assert qb_betting.match_qb_lines("C.J. Stroud", lines) == {"book": 1}
    assert qb_betting.match_qb_lines("Josh Allen", lines) == {"book": 2}
    assert qb_betting.match_qb_lines("Josh", lines) is None


# ---- player names ----------------------------------------------------------------


def test_player_name_key_normalizes_punctuation_suffixes_and_accents():
    assert player_name_key("A.J. Brown") == player_name_key("AJ Brown") == "aj brown"
    assert player_name_key("Brian Thomas Jr.") == player_name_key("Brian Thomas Jr")
    assert player_name_key("Kenneth Walker III") == "kenneth walker"
    assert player_name_key("Amon-Ra St. Brown") == "amon ra st brown"
    assert player_name_key("Ja'Marr Chase") == "jamarr chase"
    assert player_name_key("José Núñez") == "jose nunez"
    assert player_name_key(None) == ""


def test_find_by_player_name_requires_the_whole_name():
    table = {"DJ Moore": 1, "David Moore": 2}
    assert find_by_player_name("D.J. Moore", table) == 1
    assert find_by_player_name("Moore", table) is None
    assert find_by_player_name("", table) is None


def test_qb_dynamic_does_not_reproject_a_game_already_kicked_off(monkeypatch):
    session = MagicMock()
    monkeypatch.setattr(qb_dynamic, "db_session", session)
    monkeypatch.setattr(qb_dynamic, "get_nfl_season", lambda: 2026)
    monkeypatch.setattr(qb_dynamic, "get_current_nfl_week", lambda season: 9)
    monkeypatch.setattr(qb_dynamic, "_load_weekly_qb_history", lambda season: [])
    monkeypatch.setattr(
        qb_dynamic,
        "get_dynamic_starting_qbs",
        lambda season, week: [
            {
                "name": "Josh Allen",
                "team_id": 2,
                "team_name": "Buffalo Bills",
                "team_abbr": "BUF",
                "player_id": "00-1",
                "is_backup": False,
                "injury_status": "Healthy",
                "hours_to_kickoff": None,
            }
        ],
    )
    monkeypatch.setattr(
        qb_dynamic,
        "get_game_kickoff",
        lambda team, season, week: datetime(2026, 11, 8, 13, 0),
    )
    monkeypatch.setattr(qb_dynamic, "has_kicked_off", lambda kickoff: True)
    build = MagicMock()
    monkeypatch.setattr(qb_dynamic, "build_qb_prediction_context", build)

    qb_dynamic._run_qb_dynamic_core()

    build.assert_not_called()
    session.add.assert_not_called()
    session.commit.assert_not_called()
