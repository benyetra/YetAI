from app.services.etl.nfl.recv_yds_projector import project_lined_players


class _FakeQuery:
    def __init__(self, existing=None):
        self._existing = existing

    def filter_by(self, **kwargs):
        return self

    def one_or_none(self):
        return self._existing


class _FakeSession:
    def __init__(self):
        self.added = []
        self._existing = None

    def query(self, model):
        return _FakeQuery(self._existing)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        return None


def test_project_lined_players_skips_without_odds_match():
    session = _FakeSession()
    feature_rows = [
        {
            "player_id": "1",
            "player_name": "A.J. Brown",
            "position": "WR",
            "team_name": "Philadelphia Eagles",
            "opponent_team_name": "Dallas Cowboys",
            "game_date": "2026-11-15",
            "season": 2026,
            "week": 11,
            "model_yards": 100.0,
            "confidence_score": 0.8,
            "features": {},
            "model_version": "recv_nonml_v1",
        }
    ]
    stats = project_lined_players(session, feature_rows, all_lines={})
    assert stats["upserted"] == 0
    assert stats["skipped_no_line"] == 1
    assert session.added == []


def test_project_lined_players_upserts_soft_anchored_row():
    session = _FakeSession()
    feature_rows = [
        {
            "player_id": "1",
            "player_name": "A.J. Brown",
            "position": "WR",
            "team_name": "Philadelphia Eagles",
            "opponent_team_name": "Dallas Cowboys",
            "game_date": "2026-11-15",
            "season": 2026,
            "week": 11,
            "model_yards": 100.0,
            "confidence_score": 0.8,
            "features": {"target_share": 0.28},
            "model_version": "recv_nonml_v1",
        }
    ]
    all_lines = {
        "A.J. Brown": {
            "FanDuel": {
                "over": {"line": 80.0, "odds": -110},
                "under": {"line": 80.0, "odds": -110},
            }
        }
    }
    stats = project_lined_players(
        session, feature_rows, all_lines=all_lines, anchor_alpha=0.25
    )
    assert stats["upserted"] == 1
    assert len(session.added) == 1
    row = session.added[0]
    assert row.predicted_receiving_yards == 85.0
    assert row.ou_line == 80.0
    assert row.prediction_method == "soft_anchor"
    assert row.position == "WR"
