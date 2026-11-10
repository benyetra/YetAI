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
