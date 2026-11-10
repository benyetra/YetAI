from app.services.etl.nfl.recv_yds_usage import select_usage_priors_for_names


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
        schedule_by_team={
            "Philadelphia Eagles": {
                "opponent_team_name": "Dallas Cowboys",
                "game_date": "2026-11-15",
            }
        },
    )
    assert rows == []


def test_select_usage_matches_normalized_name():
    rows = select_usage_priors_for_names(
        ["AJ Brown"],
        [
            {
                "player_id": "1",
                "player_name": "A.J. Brown",
                "position": "WR",
                "team_name": "Philadelphia Eagles",
                "target_share": 0.28,
                "team_pass_attempts": 35.0,
                "receptions": 5,
                "receiving_yards": 70,
            }
        ],
        season=2026,
        week=11,
        game_date="2026-11-15",
        schedule_by_team={
            "Philadelphia Eagles": {
                "opponent_team_name": "Dallas Cowboys",
                "game_date": "2026-11-15",
            }
        },
    )
    assert len(rows) == 1
    assert rows[0]["target_share"] == 0.28
    assert rows[0]["ypr"] == 14.0


def test_select_usage_matches_odds_full_name_to_nflverse_display_name():
    """Odds slate uses full names; nflverse weekly abbreviates player_name."""
    rows = select_usage_priors_for_names(
        ["Stefon Diggs"],
        [
            {
                "player_id": "00-0031381",
                "player_name": "S.Diggs",
                "player_display_name": "Stefon Diggs",
                "position": "WR",
                "team": "WAS",
                "opponent_team": "LA",
                "week": 9,
                "target_share": 0.147,
                "targets": 5,
                "receptions": 3,
                "receiving_yards": 51,
            }
        ],
        season=2026,
        week=9,
        game_date="2026-11-10",
    )
    assert len(rows) == 1
    assert rows[0]["player_name"] == "Stefon Diggs"
    assert rows[0]["team_pass_attempts"] == 5 / 0.147
    assert rows[0]["opponent_team_name"]
