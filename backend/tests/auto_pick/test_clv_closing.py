"""Closing capture on bet rows (settlement) and the model-review CLV section."""

from datetime import date, datetime, timedelta
from statistics import NormalDist

import pytest

from app.models.database_models import BetSource, BetType, YetAIBet
from app.models.predictions_models import (
    OddsLineSnapshot,
    PointsActuals,
    PointsProjections,
)
from app.services import model_review_service as ms
from app.services.odds_math import american_to_prob
from app.services.odds_snapshots import player_key
from app.services.yetai_bets_service_db import YetAIBetsServiceDB

DAY = date(2026, 11, 12)
START = datetime(2026, 11, 13, 0, 0)  # naive UTC tip
SEEN = START - timedelta(hours=3)
LAST = START - timedelta(minutes=20)


def _snap(
    db, who, book, line, over=-110, under=-110, first=SEEN, last=LAST, event="e1"
):
    db.add(
        OddsLineSnapshot(
            sport="basketball_nba",
            event_id=event,
            commence_time=START,
            game_date=DAY,
            market="player_points",
            player_name=who,
            player_key=player_key(who),
            book=book,
            line=line,
            over_price=over,
            under_price=under,
            first_seen_at=first,
            last_seen_at=last,
        )
    )


def _bet(side, line, odds, book=None):
    pm = {"book": book} if book else {}
    return YetAIBet(
        id="b1",
        title="t",
        bet_type=BetType.PROP,
        selection="s",
        odds=odds,
        confidence=70,
        status="active",
        source=BetSource.AUTO,
        sport="NBA",
        commence_time=START,
        prediction_factors={
            "projection_metadata": pm,
            "grading": {
                "league": "NBA",
                "market": "player_prop",
                "stat": "points",
                "player": "Jayson Tatum",
                "side": side,
                "line": line,
                "game_date": DAY.isoformat(),
            },
        },
    )


@pytest.mark.parametrize("side,expected", [("over", 1.0), ("under", -1.0)])
def test_settlement_writes_closing_with_signed_line_clv(sqlite_db, side, expected):
    _snap(sqlite_db, "Jayson Tatum", "fanduel", 26.5)
    # first seen after the tip: not a close
    _snap(
        sqlite_db,
        "Jayson Tatum",
        "fanduel",
        40.5,
        first=START + timedelta(minutes=5),
        last=START + timedelta(minutes=9),
    )
    sqlite_db.commit()
    bet = _bet(side, 25.5, -115)
    f = dict(bet.prediction_factors)
    YetAIBetsServiceDB._add_closing(sqlite_db, bet, f, START + timedelta(hours=1))
    c = f["closing"]
    assert (c["book"], c["line"], c["price"], c["books"]) == ("fanduel", 26.5, -110, 1)
    assert c["line_clv"] == expected
    assert (
        c["observed_at"] == SEEN.isoformat() and c["last_seen_at"] == LAST.isoformat()
    )
    assert c["prob_clv"] is not None


def test_settlement_closing_skips_before_start_and_without_close(sqlite_db):
    bet = _bet("over", 25.5, -115)
    f = dict(bet.prediction_factors)
    YetAIBetsServiceDB._add_closing(sqlite_db, bet, f, START + timedelta(hours=1))
    assert "closing" not in f  # no snapshots yet
    _snap(sqlite_db, "Jayson Tatum", "fanduel", 26.5)
    sqlite_db.commit()
    YetAIBetsServiceDB._add_closing(sqlite_db, bet, f, START - timedelta(minutes=1))
    assert "closing" not in f  # game not started


def test_settlement_closing_falls_back_to_modal_line_when_book_has_none(sqlite_db):
    for b in ("betmgm", "caesars"):
        _snap(sqlite_db, "Jayson Tatum", b, 27.5, over=-105, under=-115)
    _snap(sqlite_db, "Jayson Tatum", "betrivers", 28.5)
    sqlite_db.commit()
    bet = _bet("over", 26.5, -110, book="draftkings")
    f = dict(bet.prediction_factors)
    YetAIBetsServiceDB._add_closing(sqlite_db, bet, f, START + timedelta(hours=1))
    c = f["closing"]
    assert (c["line"], c["price"], c["books"], c["line_clv"]) == (27.5, -105, 3, 1.0)


def test_review_clv_section_numbers_and_text(sqlite_db, monkeypatch):
    db = sqlite_db
    today = DAY + timedelta(days=1)

    def call(pid, name, side, fd_line, fd_price, actual, **best):
        kw = dict(player_name=name, projected_points=30.0)
        db.add(
            PointsProjections(
                date=DAY,
                player_id=pid,
                fanduel_line=fd_line,
                fanduel_over_under=side,
                fanduel_price=fd_price,
                **best,
                **kw,
            )
        )
        db.add(PointsActuals(date=DAY, player_id=pid, actual_points=actual, **kw))

    call(1, "Jayson Tatum", "over", 20.5, -120, 25.0)  # hit at fanduel
    call(
        2,
        "Luka Doncic",
        "under",
        20.5,
        -115,
        10.0,  # hit at the best quote
        best_book="draftkings",
        best_line=19.5,
        best_price=-105,
    )
    call(3, "No Close", "over", 20.5, -110, 30.0)  # graded, no snapshots
    _snap(db, "Jayson Tatum", "fanduel", 21.5)
    _snap(db, "Luka Doncic", "draftkings", 19.0)
    db.commit()
    monkeypatch.setattr(ms, "LOADERS", (ms._nba_props,))

    review = ms.build_review(db, today)
    k = review["clv"]["keys"][0]
    assert (k["key"], k["graded"], k["with_close"]) == ("NBA/player_prop/points", 3, 2)
    # over 20.5 vs 21.5 = +1.0; under 19.5 vs 19.0 = +0.5
    assert (k["mean_line_clv"], k["median_line_clv"]) == (0.75, 0.75)
    n = NormalDist()
    p1 = 1 - n.cdf((20.5 - 21.5) / 6.5) - american_to_prob(-120)
    p2 = n.cdf((19.5 - 19.0) / 6.5) - american_to_prob(-105)
    assert k["mean_prob_clv"] == pytest.approx((p1 + p2) / 2, abs=1e-4)
    assert k["share_prob_positive"] == 1.0
    assert k["median_minutes_before_start"] == 20.0
    assert k["priced"] == 3
    # units at the taken price: -120 hit, -105 hit, -110 hit
    assert k["units"] == pytest.approx(100 / 120 + 100 / 105 + 100 / 110, abs=0.01)

    text = ms.render_text(review)
    assert "not stored" not in text
    assert (
        "NBA/player_prop/points: 3 calls, 2 with a close; line CLV mean +0.75" in text
    )
    assert "units +2.7" in text and "breakeven" in text  # projection line too
    # steals-style key with no snapshots shows counts and the note
    assert "no snapshot join yet" in text
