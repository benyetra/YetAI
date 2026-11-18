from app.services.etl._spread_model import NFL_CONFIG
from app.services.etl.nba.market_anchor import Anchor
from app.services.etl.nfl.spread_projector import _project_spread_row


# Behaviour change (anchor build): the published margin is anchored to the line and a
# call needs a proven record. These tests assume a fully trusted model (k=1) and a
# winning record so they still check the raw Elo/PPG margin and the edge threshold.
TRUSTED = dict(anchor=Anchor(1.0, 0.0, 200), record=(40, 60))


def _ppg(off: float, def_: float) -> dict[str, tuple[float, float]]:
    return {
        "Kansas City Chiefs": (off, def_),
        "Baltimore Ravens": (off, def_),
    }


def test_spread_recommends_home_at_plus_three_edge():
    # Home favored by 3 on the board; model sees 6-point home margin → edge +3.
    row = _project_spread_row(
        home_team_name="Kansas City Chiefs",
        away_team_name="Baltimore Ravens",
        spread_home=-3.0,
        elos={"Kansas City Chiefs": 1600.0, "Baltimore Ravens": 1400.0},
        ppg_stats=_ppg(24.0, 20.0),
        **TRUSTED,
    )
    assert row["edge"] is not None
    assert row["edge"] >= NFL_CONFIG.edge_threshold
    assert row["recommendation"] == "HOME"


def test_spread_recommends_away_at_minus_three_edge():
    # Away favored by 3; model sees a larger away margin → edge <= -3.
    row = _project_spread_row(
        home_team_name="Kansas City Chiefs",
        away_team_name="Baltimore Ravens",
        spread_home=3.0,
        elos={"Kansas City Chiefs": 1300.0, "Baltimore Ravens": 1700.0},
        ppg_stats=_ppg(20.0, 24.0),
        **TRUSTED,
    )
    assert row["edge"] is not None
    assert row["edge"] <= -NFL_CONFIG.edge_threshold
    assert row["recommendation"] == "AWAY"


def test_spread_no_play_within_threshold():
    row = _project_spread_row(
        home_team_name="Kansas City Chiefs",
        away_team_name="Baltimore Ravens",
        spread_home=-2.5,
        elos={"Kansas City Chiefs": 1500.0, "Baltimore Ravens": 1500.0},
        ppg_stats=_ppg(22.5, 22.5),
        **TRUSTED,
    )
    assert row["recommendation"] == "NO_PLAY"


def test_game_with_no_time_is_started_from_0930_et_on_its_game_day():
    from datetime import date, datetime
    from types import SimpleNamespace

    from app.services.etl.nfl.spread_projector import unstarted_games

    sunday = SimpleNamespace(game_time=None, game_date=date(2026, 11, 15))
    tomorrow = SimpleNamespace(game_time=None, game_date=date(2026, 11, 16))
    timed = SimpleNamespace(
        game_time=datetime(2026, 11, 15, 22, 0), game_date=date(2026, 11, 15)
    )
    # 14:30 UTC = 09:30 ET on Sunday 11-15
    assert unstarted_games([sunday, tomorrow], now=datetime(2026, 11, 15, 14, 29)) == [
        sunday,
        tomorrow,
    ]
    assert unstarted_games([sunday, tomorrow], now=datetime(2026, 11, 15, 14, 30)) == [
        tomorrow
    ]
    # a game with its own kickoff time keeps using it (22:00 UTC not reached)
    assert unstarted_games([timed], now=datetime(2026, 11, 15, 18, 0)) == [timed]
