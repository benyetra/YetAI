from app.services.etl.nfl.recv_yds_features import build_recv_feature_row


def _base_player(**overrides):
    row = {
        "player_id": "00-0035676",
        "player_name": "A.J. Brown",
        "position": "WR",
        "team_name": "Philadelphia Eagles",
        "opponent_team_name": "Dallas Cowboys",
        "game_date": "2026-11-15",
        "season": 2026,
        "week": 11,
        "target_share": 0.28,
        "team_pass_attempts": 35.0,
        "ypr": 14.0,
        "adot": 11.0,
        "ou_line": 72.5,  # must NEVER be used as a target prior
    }
    row.update(overrides)
    return row


def test_build_recv_feature_row_computes_model_yards():
    out = build_recv_feature_row(_base_player())
    assert out is not None
    assert out["expected_targets"] == 0.28 * 35.0
    assert out["model_yards"] > 0
    assert out["position"] == "WR"
    assert (
        "ou_line" not in (out.get("features") or {})
        or out["features"].get("targets_from_line") is not True
    )


def test_build_recv_feature_row_skips_missing_targets():
    assert build_recv_feature_row(_base_player(target_share=None)) is None
    assert build_recv_feature_row(_base_player(team_pass_attempts=None)) is None


def test_build_recv_feature_row_skips_qb_and_unknown():
    assert build_recv_feature_row(_base_player(position="QB")) is None
    assert build_recv_feature_row(_base_player(position="UNK")) is None


def test_build_recv_feature_row_does_not_derive_targets_from_line():
    # Even with a fat line and missing share, skip — never invent.
    assert (
        build_recv_feature_row(_base_player(target_share=None, ou_line=120.5)) is None
    )
