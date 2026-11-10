from app.services.etl.nfl.recv_yds_weekly import _run_core


class _FakeSession:
    def __init__(self):
        self.added = []
        self.committed = False

    def query(self, model):
        class Q:
            def filter_by(self, **kw):
                return self

            def one_or_none(self):
                return None

        return Q()

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        return None

    def commit(self):
        self.committed = True


def test_run_core_upserts_lined_soft_anchor():
    session = _FakeSession()
    result = _run_core(
        session,
        fetch_lines=lambda: {
            "A.J. Brown": {
                "FanDuel": {
                    "over": {"line": 80.0, "odds": -110},
                    "under": {"line": 80.0, "odds": -110},
                }
            }
        },
        load_priors=lambda names: [
            {
                "player_id": "1",
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
                "snap_pct": 0.9,
                "game_env": {"implied_team_pass_attempts": 36.0},
                "opponent_defense": {"wr_recv_yards_index": 1.05},
            }
        ],
    )
    assert result["upserted"] == 1
    assert session.committed is True
    assert session.added[0].prediction_method == "soft_anchor"
    assert session.added[0].predicted_receiving_yards != session.added[0].ou_line
