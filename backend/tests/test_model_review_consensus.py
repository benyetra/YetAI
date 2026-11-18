"""Review reads the stored best_* quote for game lines and NFL / NHL props (B4)."""

from datetime import date, datetime, timedelta
from statistics import NormalDist
from types import SimpleNamespace

import pytest

from app.models.predictions_models import (
    NBAGameLines,
    NBASpreadActuals,
    NBASpreadProjections,
)
from app.services import model_review_service as ms
from tests.auto_pick.conftest import sqlite_db  # noqa: F401  (fixture)

D = date(2026, 11, 10)
KEY = ("NBA", "spread", "version v1")


def _spread(proj, home_pt, actual, best=None, side=None, **kw):
    """A spread review row: stored line = home margin the market asks (-home point)."""
    extra = {"best": best, "best_side": side} if best else {}
    return ms._row(
        proj,
        -home_pt,
        actual,
        "HOME" if proj + home_pt > 0 else "AWAY",
        ("t", D, "Home", "Away"),
        "Away @ Home",
        correct=None,
        version="v1",
        **extra,
        **kw,
    )


def test_away_spread_quote_is_graded_on_its_own_line():
    # Stored home -3.5, but the quote is away +4.5 at -105: away loses by 4 -> covers.
    # (graded at -3.5 it would be a miss: home margin 4 > 3.5)
    row = _spread(-2, -3.5, 4, ("book", 4.5, -105), "away")
    rec = ms._current_record("edge", [row])
    assert rec["priced"] == 1
    assert rec["units"] == pytest.approx(0.95)


def test_push_at_the_quote_number_is_not_a_priced_call():
    # away +4 and the home side wins by exactly 4
    row = _spread(-2, -3.5, 4, ("book", 4.0, -110), "away")
    rec = ms._current_record("edge", [row])
    assert (rec["priced"], rec["units"]) == (None, None)  # a push is no call, no units


def test_spread_without_best_quote_stays_unpriced():
    rec = ms._current_record("edge", [_spread(-2, -3.5, 4)])
    assert rec["priced"] is None and rec["units"] is None


def _ou(proj, line, actual, pick, **kw):
    return ms._row(proj, line, actual, pick, ("t", D, "A", "B"), "A @ B", **kw)


def test_total_graded_at_best_line_not_stored_line():
    # projection 50 is OVER the stored 47.5; quote: over 44.5 at +100 (best_line differs).
    # actual 46: loses at the stored 47.5, WINS at the quote's 44.5.
    row = _ou(50, 47.5, 46, "over", best=("b", 44.5, 100), best_side="over")
    rec = ms._current_record("ou", [row])
    assert (rec["calls"], rec["hits"]) == (1, 0)  # the call stays on the stored line
    assert (rec["priced"], rec["units"]) == (1, 1.0)


def test_nhl_saves_quote_on_the_other_side_is_not_priced_at_this_side():
    row = _ou(
        28,
        26.5,
        30,
        "over",
        over_price=-120,
        under_price=100,
        best=("b", 27.5, 105),
        best_side="under",
    )
    rec = ms._current_record("ou", [row])
    assert rec["priced"] == 0 and rec["units"] == 0.0


def test_loader_carries_best_quote_and_event_id(sqlite_db):  # noqa: F811
    db = sqlite_db
    db.add(
        NBASpreadProjections(
            game_date=D,
            home_team_name="Home",
            away_team_name="Away",
            projected_margin=1.0,
            home_win_prob=0.55,
            market_spread_home=-3.5,
            recommendation="AWAY",
            model_version="v1",
            best_book="book",
            best_line=3.5,
            best_price=-105,
            best_side="away",
        )
    )
    db.add(
        NBASpreadActuals(
            game_date=D,
            home_team_name="Home",
            away_team_name="Away",
            home_score=100,
            away_score=97,
            actual_margin=3,
            home_won=True,
        )
    )
    db.add(
        NBAGameLines(
            game_date=D,
            home_team_name="Home",
            away_team_name="Away",
            odds_api_event_id="ev1",
        )
    )
    db.commit()
    ((_, rows),) = ms._nba_spread(db, D, D).values()
    r = rows[0]
    assert r["best"] == ("book", 3.5, -105) and r["best_side"] == "away"
    assert r["event_id"] == "ev1"
    # away +3.5, home wins by 3: away covers
    assert ms._current_record("edge", rows)["priced"] == 1


def _snap(i, book, home_pt, first, commence, event="ev1"):
    return SimpleNamespace(
        id=i,
        book=book,
        line=home_pt,
        over_price=None,
        under_price=None,
        home_price=-110,
        away_price=-110,
        first_seen_at=first,
        last_seen_at=commence - timedelta(minutes=5),
        commence_time=commence,
        home_team="Home",
        away_team="Away",
    )


def test_spread_clv_for_the_quotes_side_and_no_close_is_counted():
    commence = datetime(2026, 11, 11, 0, 0)
    at = commence - timedelta(hours=6)
    obs = []
    for n, book in enumerate(("a", "b", "c")):
        obs.append(_snap(n, book, -4.5, commence - timedelta(hours=8), commence))
        obs.append(_snap(10 + n, book, -5.5, commence - timedelta(hours=1), commence))
    # event ev2 was only seen after the start: no close
    late = [_snap(99, "a", -4.5, commence + timedelta(hours=1), commence, "ev2")]
    idx = {(D, "spreads", "", "ev1"): obs, (D, "spreads", "", "ev2"): late}
    # away quote at +4.5 (home -4.5) taken at `at`; the market then moved to home -5.5
    q = ("a", 4.5, -110)
    rows = [
        _spread(-2, -4.5, -10, q, "away", at=at, event_id="ev1"),
        _spread(-2, -4.5, -10, q, "away", at=at, event_id="ev2"),
    ]
    out = ms._clv_for_key(KEY, rows, idx)
    assert (out["graded"], out["with_close"]) == (2, 1)
    # under the home margin at 4.5: P(under | center 5.5) - P(under | center 4.5)
    want = NormalDist().cdf((4.5 - 5.5) / 12.0) - 0.5
    assert out["mean_prob_clv"] == pytest.approx(want, abs=1e-4)
    assert out["mean_line_clv"] == pytest.approx(-1.0)  # under: taken 4.5, closed 5.5


def test_game_rows_without_best_quote_are_not_graded_for_clv():
    out = ms._clv_for_key(KEY, [_spread(-2, -4.5, -10)], {})
    assert out["graded"] == 0 and out["no_best_quote"] == 1
