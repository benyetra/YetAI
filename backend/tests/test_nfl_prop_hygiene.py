from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from app.services.etl.nfl import kickers, qb_dynamic


def test_get_team_opponent_ignores_preseason_rows():
    df = pd.DataFrame(
        [
            {
                "week": 1,
                "game_type": "PRE",
                "home_team": "KC",
                "away_team": "CHI",
                "gameday": "2026-08-15",
                "gametime": "20:00",
            },
            {
                "week": 1,
                "game_type": "REG",
                "home_team": "KC",
                "away_team": "BAL",
                "gameday": "2026-09-10",
                "gametime": "20:20",
            },
        ]
    )
    with patch("app.services.etl.nfl.qb_dynamic.nfl.import_schedules", return_value=df):
        assert qb_dynamic.get_team_opponent("KC", 2026, 1) == "BAL"


def test_get_game_kickoff_parses_reg_datetime():
    df = pd.DataFrame(
        [
            {
                "week": 1,
                "game_type": "REG",
                "home_team": "KC",
                "away_team": "BAL",
                "gameday": "2026-09-10",
                "gametime": "20:20",
            }
        ]
    )
    with patch("app.services.etl.nfl.qb_dynamic.nfl.import_schedules", return_value=df):
        kickoff = qb_dynamic.get_game_kickoff("KC", 2026, 1)
        assert kickoff is not None
        assert kickoff.date().isoformat() == "2026-09-10"


def test_get_team_statistics_default_uses_get_nfl_season(monkeypatch):
    monkeypatch.setattr(kickers, "get_nfl_season", lambda: 2026)
    called = []

    def fake_get(url, timeout=30):
        called.append(url)
        m = MagicMock()
        m.status_code = 200
        # Incomplete payload so we do not rely on prior-season shape here
        m.json.return_value = {"splits": {"categories": []}}
        return m

    with patch("app.services.etl.nfl.kickers.requests.get", side_effect=fake_get):
        kickers.get_team_statistics(1, fallback_prior_season=False)  # no season_year
    assert called
    assert "/seasons/2026/" in called[0]
