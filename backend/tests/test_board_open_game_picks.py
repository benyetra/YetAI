"""An OPEN game market shows its pick on the board: the stored best quote (side, line, book,
price) when the selector would pick it, nothing when it would not, and today's behaviour
when the gate withholds the key."""

from datetime import datetime

import pytest

from app.api.v1 import predictions as api
from app.models.predictions_models import (
    NBASpreadProjections,
    NBATotalsProjections,
    NFLSpreadProjections,
    NFLTotalsProjections,
    NHLTeamTotalsPredictions,
)
from app.services.auto_pick import record_gate as rg
from tests.auto_pick import test_sources_nba as nba
from tests.auto_pick import test_sources_nfl as nfl
from tests.auto_pick import test_sources_nhl as nhl
from tests.auto_pick.conftest import sqlite_db  # noqa: F401

QUOTED = datetime(2026, 1, 15, 15, 30)
FACTORS = {"anchor": {"k": 0.1}, "model_margin": 4.0}


def quote(side, line, price, fair, book="draftkings", prefix="best_"):
    out = {
        f"{prefix}book": book,
        f"{prefix}price": price,
        f"{prefix}side": side,
        f"{prefix}fair_prob": fair,
        f"{prefix}ev": 0.05,
        f"{prefix}quoted_at": QUOTED,
    }
    if line is not None:
        out[f"{prefix}line"] = line
    return out


@pytest.fixture(autouse=True)
def _db(sqlite_db):  # noqa: F811
    sqlite_db.connection().connection.create_function("timezone", 2, lambda _tz, x: x)


def _board(db, monkeypatch, sport, groups, withheld=()):
    monkeypatch.setattr(
        rg,
        "withheld_keys",
        lambda db_, now, keys, loaders: {k: "unproven_record" for k in withheld},
    )
    payload = {
        g: [api._row_to_dict(r) for r in db.query(m).all()] for g, m in groups.items()
    }
    return api._withhold_board_picks(payload, db, sport, None)


def _nba_rows(db, **kw):
    nba._gl(db)
    nba._spread(db, rec="NO_PLAY", factors=FACTORS, **kw.get("spread", {}))
    db.add(
        NBATotalsProjections(
            game_date=nba.DAY,
            home_team_name=nba.HOME,
            away_team_name=nba.AWAY,
            projected_total=231.0,
            market_total=225.5,
            edge=5.5,
            recommendation="NO_PLAY",
            created_at=datetime(2026, 1, 15, 15, 0),
            **kw.get("total", {}),
        )
    )
    db.commit()


NBA_GROUPS = {"spreads": NBASpreadProjections, "totals": NBATotalsProjections}
NBA_KEYS = {"spread": ("NBA", "spread", None), "total": ("NBA", "total", None)}


def test_nba_open_total_shows_pick_with_book_and_price(sqlite_db, monkeypatch):
    _nba_rows(
        sqlite_db,
        total=quote("over", 221.5, 105, 0.52),
        spread=quote("away", 6.0, 105, 0.50),
    )
    out = _board(sqlite_db, monkeypatch, "nba", NBA_GROUPS)
    (t,) = out["totals"]
    assert t["recommendation"] == "OVER" and "pick_withheld" not in t
    assert (t["best_line"], t["best_book"], t["best_price"]) == (
        221.5,
        "draftkings",
        105,
    )
    (s,) = out["spreads"]
    assert s["recommendation"] == "AWAY" and s["best_line"] == 6.0


def test_nba_open_but_failing_row_shows_no_pick_and_no_note(sqlite_db, monkeypatch):
    # fair 0.50 at -108: consensus EV < 0, so the selector would not pick it
    _nba_rows(sqlite_db, total=quote("over", 221.5, -108, 0.50))
    (t,) = _board(sqlite_db, monkeypatch, "nba", NBA_GROUPS)["totals"]
    assert t["recommendation"] is None and t["edge"] is None
    assert t["best_book"] is None and t["best_price"] is None
    assert "pick_withheld" not in t


def test_nba_withheld_key_is_unchanged(sqlite_db, monkeypatch):
    _nba_rows(sqlite_db, total=quote("over", 221.5, 105, 0.52))
    out = _board(
        sqlite_db, monkeypatch, "nba", NBA_GROUPS, withheld=[NBA_KEYS["total"]]
    )
    (t,) = out["totals"]
    assert t["pick_withheld"] == "unproven_record"
    assert t["recommendation"] is None and t["best_book"] is None


def test_nba_moneyline_on_a_spread_row_uses_ml_best(sqlite_db, monkeypatch):
    # spread quote fails (fair 0.45 at -110); the moneyline quote passes
    _nba_rows(
        sqlite_db,
        spread={
            **quote("away", 6.0, -110, 0.45),
            **quote("away", None, 180, 0.38, prefix="ml_best_"),
        },
    )
    sqlite_db.query(NBASpreadProjections).update({"home_win_prob": 0.4})
    (s,) = _board(sqlite_db, monkeypatch, "nba", NBA_GROUPS)["spreads"]
    assert s["recommendation"] is None and s["best_book"] is None
    assert s["ml_recommendation"] == "AWAY"
    assert (s["ml_best_price"], s["ml_best_book"]) == (180, "draftkings")
    # moneyline withheld: its quote goes, the spread decides on its own
    (s,) = _board(
        sqlite_db,
        monkeypatch,
        "nba",
        NBA_GROUPS,
        withheld=[("NBA", "moneyline", None)],
    )["spreads"]
    assert s["ml_best_price"] is None and s["ml_pick_withheld"] == "unproven_record"


def test_nfl_open_spread_and_total(sqlite_db, monkeypatch):
    nfl._line(sqlite_db)
    nfl._spread(
        sqlite_db,
        rec="NO_PLAY",
        margin=-1.0,
        factors=FACTORS,
        **quote("away", 3.0, 105, 0.52),
    )
    nfl._total(
        sqlite_db, rec="NO_PLAY", projected=45.0, **quote("under", 48.5, 105, 0.52)
    )
    groups = {"spreads": NFLSpreadProjections, "totals": NFLTotalsProjections}
    out = _board(sqlite_db, monkeypatch, "nfl", groups)
    assert out["spreads"][0]["recommendation"] == "AWAY"
    t = out["totals"][0]
    assert t["recommendation"] == "UNDER" and t["best_line"] == 48.5
    assert t["best_book"] == "draftkings" and t["best_price"] == 105
    # failing total: no pick
    sqlite_db.query(NFLTotalsProjections).update({"best_price": -120})
    t = _board(sqlite_db, monkeypatch, "nfl", groups)["totals"][0]
    assert t["recommendation"] is None and "pick_withheld" not in t
    # withheld spread: today's behaviour
    out = _board(
        sqlite_db, monkeypatch, "nfl", groups, withheld=[("NFL", "spread", None)]
    )
    assert out["spreads"][0]["pick_withheld"] == "unproven_record"


def test_nhl_open_total(sqlite_db, monkeypatch):
    nhl._totals(
        sqlite_db,
        betting_recommendation="PASS",
        predicted_total_goals=6.4,
        **quote("over", 5.5, 105, 0.52),
    )
    groups = {"team_totals": NHLTeamTotalsPredictions}
    (t,) = _board(sqlite_db, monkeypatch, "nhl", groups)["team_totals"]
    assert t["recommendation"] == "OVER" and t["betting_recommendation"] == "OVER"
    assert (t["best_line"], t["best_book"], t["best_price"]) == (5.5, "draftkings", 105)
    sqlite_db.query(NHLTeamTotalsPredictions).update({"best_price": -125})
    (t,) = _board(sqlite_db, monkeypatch, "nhl", groups)["team_totals"]
    assert t["recommendation"] is None and t["best_book"] is None
    assert "pick_withheld" not in t
    (t,) = _board(
        sqlite_db, monkeypatch, "nhl", groups, withheld=[("NHL", "total", None)]
    )["team_totals"]
    assert t["pick_withheld"] == "unproven_record"
