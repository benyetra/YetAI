"""An OPEN game market shows its pick on the board: the stored best quote (side, line, book,
price) when the selector would pick it right now (every hard gate at the real clock, the
loaded odds bounds, the EV gates), nothing when it would not, and today's behaviour when the
gate withholds the key."""

from datetime import datetime, timedelta

import pytest

from app.api.v1 import predictions as api
from app.models.database_models import ScoringConfig
from app.models.predictions_models import (
    NBASpreadProjections,
    NBATotalsProjections,
    NFLSpreadProjections,
    NFLTotalsProjections,
    NHLTeamTotalsPredictions,
)
from app.services.auto_pick import record_gate as rg
from app.services.auto_pick.candidate import latest_refresh_start
from tests.auto_pick import test_sources_nba as nba
from tests.auto_pick import test_sources_nfl as nfl
from tests.auto_pick import test_sources_nhl as nhl
from tests.auto_pick.conftest import sqlite_db  # noqa: F401

NBA_NOW = datetime(2026, 1, 15, 20, 0)  # 15:00 ET, tip 19:30 ET
NHL_NOW = NBA_NOW  # puck drop 19:00 ET
NFL_NOW = datetime(2026, 11, 15, 16, 0)  # Sunday 11:00 ET, kickoff 13:00 ET
FACTORS = {"anchor": {"k": 0.1}, "model_margin": 4.0}


def fresh(league, now):
    """A write time inside the latest refresh."""
    return latest_refresh_start(now, league) + timedelta(minutes=5)


def quote(side, line, price, fair, at, book="draftkings", prefix="best_"):
    out = {
        f"{prefix}book": book,
        f"{prefix}price": price,
        f"{prefix}side": side,
        f"{prefix}fair_prob": fair,
        f"{prefix}ev": 0.05,
        f"{prefix}quoted_at": at,
    }
    if line is not None:
        out[f"{prefix}line"] = line
    return out


@pytest.fixture(autouse=True)
def _db(sqlite_db):  # noqa: F811
    sqlite_db.connection().connection.create_function("timezone", 2, lambda _tz, x: x)


def _board(db, monkeypatch, sport, groups, now, withheld=()):
    monkeypatch.setattr(api, "_now", lambda: now)
    monkeypatch.setattr(
        rg,
        "withheld_keys",
        lambda db_, now_, keys, loaders: {k: "unproven_record" for k in withheld},
    )
    payload = {
        g: [api._row_to_dict(r) for r in db.query(m).all()] for g, m in groups.items()
    }
    return api._withhold_board_picks(payload, db, sport, None)


def _nba(db, spread=None, total=None, margin=2.0, at=None):
    at = at or fresh("NBA", NBA_NOW)
    nba._gl(db)
    nba._spread(db, rec="NO_PLAY", margin=margin, factors=FACTORS, **(spread or {}))
    db.add(
        NBATotalsProjections(
            game_date=nba.DAY,
            home_team_name=nba.HOME,
            away_team_name=nba.AWAY,
            projected_total=231.0,
            market_total=225.5,
            edge=5.5,
            recommendation="NO_PLAY",
            **(total or {}),
        )
    )
    db.commit()
    db.query(NBASpreadProjections).update({"created_at": at})
    db.query(NBATotalsProjections).update({"created_at": at})
    db.commit()


NBA_GROUPS = {"spreads": NBASpreadProjections, "totals": NBATotalsProjections}
NBA_FRESH = fresh("NBA", NBA_NOW)


def test_nba_open_total_and_spread_show_pick_with_book_price_and_why(
    sqlite_db, monkeypatch
):
    _nba(
        sqlite_db,
        total=quote("over", 221.5, 105, 0.52, NBA_FRESH),
        spread=quote("away", 6.0, 105, 0.52, NBA_FRESH),
    )
    out = _board(sqlite_db, monkeypatch, "nba", NBA_GROUPS, NBA_NOW)
    (t,) = out["totals"]
    assert t["recommendation"] == "OVER" and "pick_withheld" not in t
    assert (t["best_line"], t["best_book"], t["best_price"]) == (
        221.5,
        "draftkings",
        105,
    )
    # the pick is the price: no projector edge or strength, the consensus fair price and EV
    assert t["edge"] is None and t["value_tier"] is None
    assert t["pick_fair_prob"] == pytest.approx(0.52) and t["pick_ev"] > 0.02
    (s,) = out["spreads"]
    assert s["recommendation"] == "AWAY" and s["best_line"] == 6.0 and s["edge"] is None


def test_open_but_failing_row_shows_no_pick_and_no_note(sqlite_db, monkeypatch):
    # fair 0.50 at -108: consensus EV < 0, so the selector would not pick it
    _nba(sqlite_db, total=quote("over", 221.5, -108, 0.50, NBA_FRESH))
    (t,) = _board(sqlite_db, monkeypatch, "nba", NBA_GROUPS, NBA_NOW)["totals"]
    assert t["recommendation"] is None and t["edge"] is None
    assert t["best_book"] is None and t["best_price"] is None
    assert "pick_withheld" not in t and "pick_ev" not in t


def test_withheld_key_is_unchanged(sqlite_db, monkeypatch):
    _nba(sqlite_db, total=quote("over", 221.5, 105, 0.52, NBA_FRESH))
    out = _board(
        sqlite_db,
        monkeypatch,
        "nba",
        NBA_GROUPS,
        NBA_NOW,
        withheld=[("NBA", "total", None)],
    )
    (t,) = out["totals"]
    assert t["pick_withheld"] == "unproven_record"
    assert t["recommendation"] is None and t["best_book"] is None


def test_stale_quote_shows_no_pick(sqlite_db, monkeypatch):
    old = latest_refresh_start(NBA_NOW, "NBA") - timedelta(hours=1)
    _nba(sqlite_db, total=quote("over", 221.5, 105, 0.52, old), at=old)
    (t,) = _board(sqlite_db, monkeypatch, "nba", NBA_GROUPS, NBA_NOW)["totals"]
    assert t["recommendation"] is None and t["best_book"] is None
    assert "pick_withheld" not in t


def test_started_game_shows_no_pick(sqlite_db, monkeypatch):
    _nba(sqlite_db, total=quote("over", 221.5, 105, 0.52, NBA_FRESH))
    after_tip = datetime(2026, 1, 16, 0, 40)  # tip was 00:30 UTC
    # a quote still inside its refresh window at that clock: only the start gate fires
    sqlite_db.query(NBATotalsProjections).update(
        {
            "created_at": fresh("NBA", after_tip),
            "best_quoted_at": fresh("NBA", after_tip),
        }
    )
    (t,) = _board(sqlite_db, monkeypatch, "nba", NBA_GROUPS, after_tip)["totals"]
    assert t["recommendation"] is None and t["best_book"] is None


def test_odds_bounds_come_from_the_scoring_config(sqlite_db, monkeypatch):
    _nba(sqlite_db, total=quote("over", 221.5, 105, 0.52, NBA_FRESH))
    (t,) = _board(sqlite_db, monkeypatch, "nba", NBA_GROUPS, NBA_NOW)["totals"]
    assert t["recommendation"] == "OVER"
    sqlite_db.add(ScoringConfig(odds_min=-300, odds_max=100))  # +105 is out of bounds
    sqlite_db.commit()
    (t,) = _board(sqlite_db, monkeypatch, "nba", NBA_GROUPS, NBA_NOW)["totals"]
    assert t["recommendation"] is None and t["best_price"] is None


def test_gate_shadow_records_use_the_same_loaded_bounds(sqlite_db, monkeypatch):
    seen = []
    monkeypatch.setitem(
        rg.PROJECTION_LOADERS,
        "probe",
        lambda db, start, end: seen.append(rg.current_odds_bounds()) or {},
    )
    sqlite_db.add(ScoringConfig(odds_min=-150, odds_max=200))
    sqlite_db.commit()
    rg.load_projection_records(sqlite_db, NBA_NOW, loaders=("probe",))
    assert seen == [(-150, 200)]
    assert rg.current_odds_bounds() == (-300, 400)  # restored after the load
    rows = [
        {"best_line": 24.5, "best_price": 150, "best_fair_prob": 0.7,
         "projected_points": 30.0, "fanduel_over_under": "o"},
        {"best_line": 24.5, "best_price": 250, "best_fair_prob": 0.7,
         "projected_points": 30.0, "fanduel_over_under": "o"},
    ]  # fmt: skip
    token = rg._BOUNDS.set((-150, 200))
    try:
        kept = rg._priced_shadow_rows("points", "projected_points", rows)
    finally:
        rg._BOUNDS.reset(token)
    assert [r["best_price"] for r in kept] == [150]


def test_home_side_negative_spread_and_a_side_against_the_model(sqlite_db, monkeypatch):
    # model: home by 8 (margin 8.0); the home -6.5 quote is on the model's side
    _nba(sqlite_db, margin=8.0, spread=quote("home", -6.5, 105, 0.52, NBA_FRESH))
    (s,) = _board(sqlite_db, monkeypatch, "nba", NBA_GROUPS, NBA_NOW)["spreads"]
    assert s["recommendation"] == "HOME" and s["best_line"] == -6.5
    # the stored best side is the away team against the same model: the selector's own
    # non-positive-edge gate drops it, so the board shows no pick (never the model's lean)
    sqlite_db.query(NBASpreadProjections).update(
        {"best_side": "away", "best_line": 6.5}
    )
    (s,) = _board(sqlite_db, monkeypatch, "nba", NBA_GROUPS, NBA_NOW)["spreads"]
    assert s["recommendation"] is None and s["best_book"] is None


def test_moneyline_on_a_spread_row_uses_ml_best(sqlite_db, monkeypatch):
    # spread quote fails (fair 0.45 at -110); the moneyline quote passes
    _nba(
        sqlite_db,
        spread={
            **quote("away", 6.0, -110, 0.45, NBA_FRESH),
            **quote("away", None, 180, 0.38, NBA_FRESH, prefix="ml_best_"),
        },
    )
    sqlite_db.query(NBASpreadProjections).update({"home_win_prob": 0.4})
    (s,) = _board(sqlite_db, monkeypatch, "nba", NBA_GROUPS, NBA_NOW)["spreads"]
    assert s["recommendation"] is None and s["best_book"] is None
    assert s["ml_recommendation"] == "AWAY"
    assert (s["ml_best_price"], s["ml_best_book"]) == (180, "draftkings")
    # moneyline withheld: its quote goes, the spread decides on its own
    (s,) = _board(
        sqlite_db,
        monkeypatch,
        "nba",
        NBA_GROUPS,
        NBA_NOW,
        withheld=[("NBA", "moneyline", None)],
    )["spreads"]
    assert s["ml_best_price"] is None and s["ml_pick_withheld"] == "unproven_record"


def test_spread_fails_total_passes_keeps_the_total_pick(sqlite_db, monkeypatch):
    _nba(
        sqlite_db,
        total=quote("over", 221.5, 105, 0.52, NBA_FRESH),
        spread=quote("away", 6.0, -110, 0.45, NBA_FRESH),
    )
    out = _board(sqlite_db, monkeypatch, "nba", NBA_GROUPS, NBA_NOW)
    assert out["spreads"][0]["recommendation"] is None
    assert out["totals"][0]["recommendation"] == "OVER"


def test_nfl_open_spread_and_total_and_gates(sqlite_db, monkeypatch):
    at = fresh("NFL", NFL_NOW)
    nfl._line(sqlite_db)
    nfl._spread(
        sqlite_db,
        rec="NO_PLAY",
        margin=-1.0,
        factors=FACTORS,
        **quote("away", 3.0, 105, 0.52, at),
    )
    nfl._total(
        sqlite_db, rec="NO_PLAY", projected=45.0, **quote("under", 48.5, 105, 0.52, at)
    )
    for m in (NFLSpreadProjections, NFLTotalsProjections):
        sqlite_db.query(m).update({"created_at": at})
    sqlite_db.commit()
    groups = {"spreads": NFLSpreadProjections, "totals": NFLTotalsProjections}
    out = _board(sqlite_db, monkeypatch, "nfl", groups, NFL_NOW)
    assert out["spreads"][0]["recommendation"] == "AWAY"
    t = out["totals"][0]
    assert t["recommendation"] == "UNDER" and t["best_line"] == 48.5
    assert t["best_book"] == "draftkings" and t["best_price"] == 105
    # failing total: no pick
    sqlite_db.query(NFLTotalsProjections).update({"best_price": -120})
    t = _board(sqlite_db, monkeypatch, "nfl", groups, NFL_NOW)["totals"][0]
    assert t["recommendation"] is None and "pick_withheld" not in t
    # kickoff passed (13:00 ET): no pick
    late = datetime(2026, 11, 15, 18, 30)
    for m in (NFLSpreadProjections, NFLTotalsProjections):
        sqlite_db.query(m).update({"created_at": fresh("NFL", late)})
    sqlite_db.query(NFLSpreadProjections).update({"best_quoted_at": fresh("NFL", late)})
    s = _board(sqlite_db, monkeypatch, "nfl", groups, late)["spreads"][0]
    assert s["recommendation"] is None
    # withheld spread: today's behaviour
    out = _board(
        sqlite_db,
        monkeypatch,
        "nfl",
        groups,
        NFL_NOW,
        withheld=[("NFL", "spread", None)],
    )
    assert out["spreads"][0]["pick_withheld"] == "unproven_record"


def test_nhl_open_total(sqlite_db, monkeypatch):
    at = fresh("NHL", NHL_NOW)
    nhl._totals(
        sqlite_db,
        betting_recommendation="PASS",
        predicted_total_goals=6.4,
        **quote("over", 5.5, 105, 0.52, at),
    )
    sqlite_db.query(NHLTeamTotalsPredictions).update({"prediction_date": at})
    sqlite_db.commit()
    groups = {"team_totals": NHLTeamTotalsPredictions}
    (t,) = _board(sqlite_db, monkeypatch, "nhl", groups, NHL_NOW)["team_totals"]
    assert t["recommendation"] == "OVER" and t["betting_recommendation"] == "OVER"
    assert (t["best_line"], t["best_book"], t["best_price"]) == (5.5, "draftkings", 105)
    assert t["edge"] is None and t["pick_ev"] > 0.02
    sqlite_db.query(NHLTeamTotalsPredictions).update({"best_price": -125})
    (t,) = _board(sqlite_db, monkeypatch, "nhl", groups, NHL_NOW)["team_totals"]
    assert t["recommendation"] is None and t["best_book"] is None
    assert "pick_withheld" not in t
    (t,) = _board(
        sqlite_db,
        monkeypatch,
        "nhl",
        groups,
        NHL_NOW,
        withheld=[("NHL", "total", None)],
    )["team_totals"]
    assert t["pick_withheld"] == "unproven_record"


def test_builder_failure_fails_closed(sqlite_db, monkeypatch):
    _nba(sqlite_db, total=quote("over", 221.5, 105, 0.52, NBA_FRESH))

    def boom():
        raise ImportError("x")

    monkeypatch.setattr(api, "_game_pick_builders", boom)
    (t,) = _board(sqlite_db, monkeypatch, "nba", NBA_GROUPS, NBA_NOW)["totals"]
    assert t["recommendation"] is None and t["best_book"] is None
