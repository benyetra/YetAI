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
