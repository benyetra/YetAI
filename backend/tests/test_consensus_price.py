"""Same-line consensus and best price for game lines and NFL / NHL props (consensus_price)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import OddsLineSnapshot
from app.services import consensus_price as cp
from app.services import odds_snapshots as snaps
from app.services.fair_price import consensus, devig

NOW = datetime(2026, 11, 22, 17, 0)  # naive UTC
START = NOW + timedelta(hours=4)
EVENT = "evt1"


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    OddsLineSnapshot.__table__.create(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _event(books: dict, market: str, player=None):
    """books: {book: (point, over/home price, under/away price)}."""
    out = []
    for book, (point, a, b) in books.items():
        if market == "spreads":
            outcomes = [
                {"name": "Home", "price": a, "point": point},
                {"name": "Away", "price": b, "point": -point},
            ]
        elif market == "h2h":
            outcomes = [{"name": "Home", "price": a}, {"name": "Away", "price": b}]
        else:
            outcomes = [
                {"name": "Over", "price": a, "point": point, "description": player},
                {"name": "Under", "price": b, "point": point, "description": player},
            ]
        out.append(
            {
                "key": book,
                "markets": [
                    {
                        "key": market,
                        "last_update": NOW.isoformat() + "Z",
                        "outcomes": outcomes,
                    }
                ],
            }
        )
    return {
        "id": EVENT,
        "commence_time": START.isoformat() + "Z",
        "home_team": "Home",
        "away_team": "Away",
        "bookmakers": out,
    }


def _record(db, books, market, at=NOW, player=None):
    rows = snaps.parse_payload("americanfootball_nfl", _event(books, market, player))
    snaps.record_rows(db, rows, at)


def _fields(db, market, side, at=NOW, **kw):
    return cp.best_fields(
        db,
        event_id=EVENT,
        market=market,
        side=side,
        now=at + timedelta(minutes=5),
        **kw,
    )


def test_best_price_against_other_books_at_the_same_line_only(db):
    _record(
        db,
        {
            "draftkings": (44.5, -110, -110),
            "betmgm": (44.5, -110, -110),
            "pinnacle": (44.5, -105, -115),
            "williamhill_us": (44.5, -112, -108),
            "fanduel": (44.5, +105, -125),
            # another line: never in the consensus, never compared
            "espnbet": (45.5, +150, -190),
        },
        "totals",
    )
    f = _fields(db, "totals", "o", side_name="over")
    assert (f["best_book"], f["best_line"], f["best_price"]) == ("fanduel", 44.5, 105)
    others = {
        b: devig.two_way(o, u)[0]
        for b, (o, u) in {
            "draftkings": (-110, -110),
            "betmgm": (-110, -110),
            "pinnacle": (-105, -115),
            "williamhill_us": (-112, -108),
        }.items()
    }
    assert f["best_fair_prob"] == pytest.approx(consensus.blend(others, None))
    assert f["best_ev"] == pytest.approx(f["best_fair_prob"] * 2.05 - 1)
    assert f["best_side"] == "over"
    assert f["best_quoted_at"] == NOW


def test_a_book_at_a_different_spread_is_ignored(db):
    # Three books at -3.5 and one at -3: the -3 book is a different bet. With it the
    # -3.5 books would each have 3 others only if -3 counted.
    _record(
        db,
        {
            "draftkings": (-3.5, -110, -110),
            "betmgm": (-3.5, -108, -112),
            "fanduel": (-3.5, -105, -115),
            "williamhill_us": (-3.0, +120, -150),
        },
        "spreads",
    )
    assert _fields(db, "spreads", "o")["best_book"] is None  # 2 others at -3.5
    assert _fields(db, "spreads", "u")["best_book"] is None


def test_fewer_than_three_other_books_is_no_consensus(db):
    _record(
        db,
        {
            "draftkings": (6.5, -110, -110),
            "betmgm": (6.5, -110, -110),
            "fanduel": (6.5, +100, -120),
        },
        "totals",
    )
    f = _fields(db, "totals", "o")
    assert set(f.values()) == {None}
    assert set(f) == {"best_" + n for n in cp.FIELDS}


def test_reference_only_books_count_in_the_consensus_but_are_never_best(db):
    _record(
        db,
        {
            "pinnacle": (0, +200, -240),  # best price, but not bettable
            "draftkings": (0, +150, -170),
            "betmgm": (0, +150, -170),
            "williamhill_us": (0, +145, -165),
            "fanduel": (0, +155, -180),
        },
        "h2h",
    )
    f = _fields(db, "h2h", "o", prefix="ml_best_", with_line=False, side_name="home")
    assert f["ml_best_book"] == "fanduel" and f["ml_best_price"] == 155
    assert "ml_best_line" not in f and f["ml_best_side"] == "home"


def test_away_spread_is_stored_as_the_away_line(db):
    books = {b: (-3.5, -110, -110) for b in ("draftkings", "betmgm", "pinnacle")}
    books["fanduel"] = (-3.5, -120, +100)
    _record(db, books, "spreads")
    f = _fields(db, "spreads", "u", side_name="away")
    assert (f["best_book"], f["best_line"], f["best_price"]) == ("fanduel", 3.5, 100)


def test_stale_quotes_refused_capture_give_no_consensus(db):
    books = {b: (44.5, -110, -110) for b in ("draftkings", "betmgm", "pinnacle")}
    books["fanduel"] = (44.5, +105, -125)
    _record(db, books, "totals", at=NOW - timedelta(hours=3))
    # The 3-hours-old capture is all there is (this refresh's fetch was refused).
    assert set(_fields(db, "totals", "o").values()) == {None}
    # A fresh fetch (same quotes) moves last_seen_at, and the consensus is back.
    _record(db, books, "totals", at=NOW)
    assert _fields(db, "totals", "o")["best_book"] == "fanduel"


def test_on_side_limits_the_lines(db):
    books = {b: (44.5, -110, -110) for b in ("draftkings", "betmgm", "pinnacle")}
    books["fanduel"] = (44.5, +105, -125)
    _record(db, books, "totals")
    assert (
        _fields(db, "totals", "o", on_side=lambda line: 44.0 > line)["best_book"]
        is None
    )


def test_player_prop_matches_the_player_and_its_line(db):
    books = {b: (245.5, -110, -110) for b in ("draftkings", "betmgm", "williamhill_us")}
    books["fanduel"] = (245.5, -110, +102)
    _record(db, books, "player_pass_yds", player="Patrick Mahomes")
    f = _fields(db, "player_pass_yds", "u", player="Patrick Mahomes")
    assert (f["best_book"], f["best_price"]) == ("fanduel", 102)
    assert _fields(db, "player_pass_yds", "u", player="Josh Allen")["best_book"] is None
    # game-market read never picks up player rows
    assert _fields(db, "player_pass_yds", "u")["best_book"] is None


def test_no_event_or_side_is_no_consensus(db):
    assert set(
        cp.best_fields(db, event_id=None, market="totals", side="o").values()
    ) == {None}
    assert set(
        cp.best_fields(db, event_id=EVENT, market="totals", side=None).values()
    ) == {None}


def test_a_book_missing_from_the_newest_fetch_is_never_best(db):
    # Four books at -110/-110 seen now; DraftKings +125 was last seen 29 minutes earlier
    # (it pulled the market): it still counts nowhere as the best price.
    books = {
        b: (44.5, -110, -110)
        for b in ("betmgm", "pinnacle", "williamhill_us", "espnbet")
    }
    _record(
        db, {"draftkings": (44.5, +125, -150)}, "totals", at=NOW - timedelta(minutes=29)
    )
    _record(db, books, "totals", at=NOW)
    f = _fields(db, "totals", "o")
    assert f["best_book"] != "draftkings"


def test_a_book_whose_market_lags_is_never_best(db):
    books = {b: (44.5, -110, -110) for b in ("betmgm", "pinnacle", "williamhill_us")}
    books["fanduel"] = (44.5, +130, -160)
    ev = _event(books, "totals")
    for bk in ev["bookmakers"]:
        if bk["key"] == "fanduel":  # FanDuel's own update is 20 minutes behind
            bk["markets"][0]["last_update"] = (
                NOW - timedelta(minutes=20)
            ).isoformat() + "Z"
    snaps.record_rows(db, snaps.parse_payload("americanfootball_nfl", ev), NOW)
    assert _fields(db, "totals", "o")["best_book"] != "fanduel"
