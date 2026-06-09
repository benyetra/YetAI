import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

from app.services.auto_pick.candidate import DateRange
from app.services.auto_pick.sources.wnba_player_prop_source import WNBAPlayerPropSource
from app.services.auto_pick.sources.wnba_spread_source import WNBASpreadSource
from app.services.auto_pick.sources.wnba_totals_source import WNBATotalsSource


def _date_range():
    today = date.today()
    return DateRange(
        start=datetime.combine(today, datetime.min.time()),
        end=datetime.combine(today + timedelta(days=1), datetime.min.time()),
    )


def test_wnba_totals_source_returns_candidates():
    row = MagicMock()
    row.game_date = date.today()
    row.home_team_name = "Las Vegas Aces"
    row.away_team_name = "Seattle Storm"
    row.projected_total = 168.5
    row.market_total = 165.5
    row.recommendation = "OVER"
    row.confidence_score = 72.0
    row.edge = 3.0
    row.injury_report = None
    row.factors = None
    row.created_at = datetime.utcnow()

    gl = MagicMock()
    gl.game_date = row.game_date
    gl.home_team_name = row.home_team_name
    gl.away_team_name = row.away_team_name
    gl.odds_api_event_id = "wnba-event-1"
    gl.over_odds = -115
    gl.under_odds = -105
    gl.game_time = datetime.utcnow()

    db = MagicMock()
    totals_q = MagicMock()
    totals_q.filter.return_value.all.return_value = [row]
    lines_q = MagicMock()
    lines_q.filter.return_value.all.return_value = [gl]

    def query_side(model):
        name = getattr(model, "__name__", str(model))
        if "Totals" in name:
            return totals_q
        return lines_q

    db.query.side_effect = query_side

    results = asyncio.run(WNBATotalsSource(db).get_todays_projections(_date_range()))
    assert len(results) == 1
    assert results[0]["league"] == "WNBA"
    assert results[0]["side"] == "over"
    assert results[0]["line_odds"] == -115


def test_wnba_spread_source_returns_candidates():
    row = MagicMock()
    row.game_date = date.today()
    row.home_team_name = "New York Liberty"
    row.away_team_name = "Connecticut Sun"
    row.projected_margin = 4.5
    row.market_spread_home = -3.5
    row.recommendation = "HOME"
    row.confidence_score = 68.0
    row.edge = 1.0
    row.home_win_prob = 0.62
    row.factors = None
    row.created_at = datetime.utcnow()

    gl = MagicMock()
    gl.odds_api_event_id = "wnba-event-2"
    gl.spread_home_odds = -110
    gl.spread_away_odds = -110
    gl.game_time = datetime.utcnow()

    db = MagicMock()
    spread_q = MagicMock()
    spread_q.filter.return_value.all.return_value = [row]
    lines_q = MagicMock()
    lines_q.filter.return_value.all.return_value = [gl]

    def query_side(model):
        name = getattr(model, "__name__", str(model))
        if "Spread" in name:
            return spread_q
        return lines_q

    db.query.side_effect = query_side

    results = asyncio.run(WNBASpreadSource(db).get_todays_projections(_date_range()))
    assert len(results) == 1
    assert results[0]["league"] == "WNBA"
    assert results[0]["side"] == "home"


def test_wnba_player_prop_source_skips_rows_without_market_line():
    row = MagicMock()
    row.date = date.today()
    row.player_id = 42
    row.player_name = "A'ja Wilson"
    row.projected_points = 22.5
    row.market_line = None
    row.recommendation = "OVER"
    row.confidence_score = 80.0
    row.opponent_team_name = "Storm"

    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [row]

    results = asyncio.run(
        WNBAPlayerPropSource(db).get_todays_projections(_date_range())
    )
    assert results == []


def test_wnba_player_prop_source_returns_points_prop():
    row = MagicMock()
    row.date = date.today()
    row.player_id = 42
    row.player_name = "A'ja Wilson"
    row.projected_points = 22.5
    row.market_line = 20.5
    row.recommendation = "OVER"
    row.confidence_score = 80.0
    row.opponent_team_name = "Storm"

    db = MagicMock()

    def query_side(model):
        name = getattr(model, "__name__", str(model))
        q = MagicMock()
        if "Points" in name:
            q.filter.return_value.all.return_value = [row]
        else:
            q.filter.return_value.all.return_value = []
        return q

    db.query.side_effect = query_side

    results = asyncio.run(
        WNBAPlayerPropSource(db).get_todays_projections(_date_range())
    )
    assert len(results) == 1
    assert results[0]["league"] == "WNBA"
    assert results[0]["stat"] == "points"
    assert results[0]["side"] == "over"
    assert "wnba-prop" in results[0]["event_id"]
