"""NBA today_active_players asks ESPN for today's Eastern slate, not the live default."""

from datetime import date
from unittest.mock import MagicMock, patch

from app.services.etl.nba import today_active_players as tap

TODAY = date(2026, 10, 27)


def _run(games):
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    with (
        patch.object(tap, "now_eastern") as ne,
        patch.object(tap, "fetch_games_for_date", return_value=games) as fg,
        patch.object(tap, "build_matchups", return_value=(set(), {})),
        patch.object(tap, "SessionLocal", return_value=db),
    ):
        ne.return_value.date.return_value = TODAY
        result = tap.run()
    return result, fg


def test_requests_scoreboard_for_todays_eastern_date():
    _result, fg = _run([{"home_team_id": 1, "away_team_id": 2}])
    fg.assert_called_once_with(TODAY)


def test_keeps_existing_rows_when_espn_has_no_games():
    result, _fg = _run([])
    assert result["kept_stale"] is True
    assert result["games"] == 0
