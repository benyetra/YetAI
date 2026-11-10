from datetime import datetime

from app.services.etl.nfl.recv_yds_usage import (
    LEAGUE_PASS_ATTEMPTS,
    YARDS_PER_TARGET_PRIOR,
    projected_team_pass_attempts,
    schedule_by_team_for_week,
    select_usage_priors_for_names,
    team_pass_attempts_by_game,
    usage_from_games,
)


def _game(week, *, targets, receptions, yards, season=2026, team="PHI", opp="DAL"):
    return {
        "player_id": "00-1",
        "player_name": "A.Brown",
        "player_display_name": "A.J. Brown",
        "position": "WR",
        "season": season,
        "week": week,
        "team": team,
        "opponent_team": opp,
        "targets": targets,
        "receptions": receptions,
        "receiving_yards": yards,
    }


def _qb(week, attempts, *, season=2026, team="PHI"):
    return {
        "player_id": "00-9",
        "player_display_name": "Jalen Hurts",
        "position": "QB",
        "season": season,
        "week": week,
        "team": team,
        "attempts": attempts,
    }


def _schedule(opp="NYG"):
    return {"PHI": {"opponent_abbr": opp, "game_date": "2026-11-15"}}


def test_select_usage_skips_missing_share_and_never_uses_line():
    rows = select_usage_priors_for_names(
        ["A.J. Brown"],
        [
            {
                "player_id": "1",
                "player_name": "A.J. Brown",
                "position": "WR",
                "team_name": "Philadelphia Eagles",
                "opponent_team_name": "Dallas Cowboys",
                "target_share": None,
                "team_pass_attempts": 35.0,
                "ypr": 14.0,
                "ou_line": 120.5,  # must be ignored
            }
        ],
        season=2026,
        week=11,
        game_date="2026-11-15",
    )
    assert rows == []


def test_select_usage_matches_odds_spelling_to_nflverse_display_name():
    weekly = [_game(9, targets=8, receptions=5, yards=60), _qb(9, 32)]
    for odds_name in ("AJ Brown", "A.J. Brown", "A.J. Brown Jr."):
        rows = select_usage_priors_for_names(
            [odds_name], weekly, season=2026, week=10, game_date="2026-11-15"
        )
        assert len(rows) == 1
        assert rows[0]["player_name"] == "A.J. Brown"


def test_usage_aggregates_games_instead_of_reading_the_last_one():
    # One blow-up game after eight ordinary ones must not become the projection.
    weekly = []
    for week in range(1, 9):
        weekly += [_game(week, targets=6, receptions=4, yards=48), _qb(week, 30)]
    weekly += [_game(9, targets=14, receptions=11, yards=190), _qb(9, 40)]
    (row,) = select_usage_priors_for_names(
        ["A.J. Brown"], weekly, season=2026, week=10, game_date="2026-11-15"
    )
    targets = row["target_share"] * row["team_pass_attempts"]
    yards = targets * row["yards_per_target"]
    assert 6.0 < targets < 9.0  # last game alone says 14
    assert 45.0 < yards < 80.0  # last game alone says 190
    assert row["current_season_games"] == 9


def test_usage_excludes_the_slate_week_and_later_games():
    weekly = [
        _game(8, targets=6, receptions=4, yards=50),
        _qb(8, 30),
        _game(9, targets=20, receptions=18, yards=300),  # this week's own game
        _qb(9, 30),
    ]
    (row,) = select_usage_priors_for_names(
        ["A.J. Brown"], weekly, season=2026, week=9, game_date="2026-11-08"
    )
    assert row["current_season_games"] == 1
    assert row["games"] == 1


def test_usage_uses_last_season_at_a_discount_before_any_current_games():
    weekly = [
        _game(17, targets=10, receptions=7, yards=90, season=2025),
        _qb(17, 34, season=2025),
    ]
    (row,) = select_usage_priors_for_names(
        ["A.J. Brown"], weekly, season=2026, week=1, game_date="2026-09-13"
    )
    assert row["current_season_games"] == 0
    assert row["games"] == 1
    # No current-season team games yet: pass volume is the league average.
    assert abs(row["team_pass_attempts"] - LEAGUE_PASS_ATTEMPTS) < 1e-9


def test_usage_ignores_seasons_older_than_last_year():
    weekly = [_game(5, targets=10, receptions=7, yards=90, season=2024)]
    assert (
        select_usage_priors_for_names(
            ["A.J. Brown"], weekly, season=2026, week=3, game_date="2026-09-27"
        )
        == []
    )


def test_opponent_and_date_come_from_this_weeks_schedule():
    weekly = [_game(9, targets=8, receptions=5, yards=60, opp="DAL"), _qb(9, 32)]
    (row,) = select_usage_priors_for_names(
        ["A.J. Brown"],
        weekly,
        season=2026,
        week=10,
        game_date="2026-11-10",
        schedule_by_team=_schedule("NYG"),
    )
    assert "Giants" in row["opponent_team_name"]  # not last week's Cowboys
    assert row["game_date"] == "2026-11-15"
    assert "Eagles" in row["team_name"]


def test_player_is_skipped_when_team_is_not_on_this_weeks_schedule():
    weekly = [_game(9, targets=8, receptions=5, yards=60), _qb(9, 32)]
    rows = select_usage_priors_for_names(
        ["A.J. Brown"],
        weekly,
        season=2026,
        week=10,
        game_date="2026-11-10",
        schedule_by_team={"DAL": {"opponent_abbr": "NYG", "game_date": "2026-11-15"}},
    )
    assert rows == []  # bye week or already kicked off


def test_opponent_is_tbd_without_a_schedule():
    weekly = [_game(9, targets=8, receptions=5, yards=60, opp="DAL"), _qb(9, 32)]
    (row,) = select_usage_priors_for_names(
        ["A.J. Brown"], weekly, season=2026, week=10, game_date="2026-11-10"
    )
    assert row["opponent_team_name"] == "TBD"


def test_usage_from_games_shrinks_yards_per_target_to_position_average():
    games = [
        {
            "season": 2026,
            "targets": 2.0,
            "receptions": 2.0,
            "receiving_yards": 80.0,  # 40 yards a target on two looks
            "team_attempts": 30.0,
        }
    ]
    usage = usage_from_games(games, season=2026, position="WR")
    assert YARDS_PER_TARGET_PRIOR["WR"] < usage["yards_per_target"] < 12.0
    assert usage["catch_rate"] == 1.0


def test_usage_from_games_weights_recent_and_current_season_games_more():
    old = {
        "season": 2025,
        "targets": 2.0,
        "receptions": 1.0,
        "receiving_yards": 10.0,
        "team_attempts": 30.0,
    }
    new = {**old, "season": 2026, "targets": 10.0}
    usage = usage_from_games([old, new], season=2026, position="WR")
    assert usage["target_share"] > (2.0 + 10.0) / 60.0  # closer to the recent 1/3


def test_team_pass_attempts_sum_every_passer():
    weekly = [_qb(3, 28), {**_qb(3, 6), "player_id": "00-8"}, _qb(4, 35)]
    totals = team_pass_attempts_by_game(weekly)
    assert totals[(2026, 3, "PHI")] == 34
    assert totals[(2026, 4, "PHI")] == 35


def test_projected_team_pass_attempts_blends_with_league_average():
    totals = {(2026, week, "PHI"): 40.0 for week in range(1, 7)}
    projected = projected_team_pass_attempts("PHI", totals, season=2026, week=7)
    assert LEAGUE_PASS_ATTEMPTS < projected < 40.0
    assert projected_team_pass_attempts("PHI", {}, season=2026, week=7) == (
        LEAGUE_PASS_ATTEMPTS
    )


def test_schedule_by_team_drops_other_weeks_and_kicked_off_games():
    schedule = [
        {
            "week": 10,
            "game_type": "REG",
            "home_team": "NYG",
            "away_team": "WAS",
            "gameday": "2026-11-12",
            "gametime": "20:15",
        },
        {
            "week": 10,
            "game_type": "REG",
            "home_team": "DAL",
            "away_team": "SF",
            "gameday": "2026-11-15",
            "gametime": "16:25",
        },
        {
            "week": 11,
            "game_type": "REG",
            "home_team": "PHI",
            "away_team": "DAL",
            "gameday": "2026-11-22",
            "gametime": "13:00",
        },
    ]
    out = schedule_by_team_for_week(schedule, week=10, now=datetime(2026, 11, 13, 9, 0))
    assert set(out) == {"DAL", "SF"}  # Thursday's game is final
    assert out["SF"] == {
        "opponent_abbr": "DAL",
        "game_date": "2026-11-15",
        "home": False,
    }
