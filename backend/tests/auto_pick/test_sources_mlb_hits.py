import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

from app.services.auto_pick.candidate import DateRange
from app.services.auto_pick.sources.mlb_hits_source import MLBHitsSource


def _date_range():
    today = date.today()
    return DateRange(
        start=datetime.combine(today, datetime.min.time()),
        end=datetime.combine(today + timedelta(days=1), datetime.min.time()),
    )


def _fake_hitter(**kwargs):
    r = MagicMock()
    r.player_id = kwargs.get("player_id", "123")
    r.player_name = kwargs.get("player_name", "Aaron Judge")
    r.game_id = kwargs.get("game_id", 77701)
    r.game_time = kwargs.get(
        "game_time", datetime.combine(date.today(), datetime.min.time())
    )
    r.combined_score = kwargs.get("combined_score", 3.5)
    r.hits_last_10_games = kwargs.get("hits_last_10_games", 8)
    r.team = kwargs.get("team", "NYY")
    r.opponent = kwargs.get("opponent", "BOS")
    return r


def test_mlb_hits_source_returns_parlay_eligible_candidates():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [_fake_hitter()]

    source = MLBHitsSource(db)
    results = asyncio.run(source.get_todays_projections(_date_range()))

    assert len(results) == 1
    r = results[0]
    assert r["stat"] == "hits"
    assert r["side"] == "over"
    assert r["line"] == 0.5
    assert r["parlay_eligible"] is True
    assert "mlb-hit" in r["event_id"]


def test_mlb_hits_source_skips_low_board_score():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        _fake_hitter(combined_score=1.5)
    ]

    source = MLBHitsSource(db)
    results = asyncio.run(source.get_todays_projections(_date_range()))

    assert results == []
