"""Side rules + best_* for the projection writers (etl/_consensus_attach), on real
snapshot rows in sqlite. Writers call best_fields with the real clock, so the snapshots
are seeded relative to utcnow()."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import NFLGameLines, OddsLineSnapshot
from app.services import odds_snapshots as snaps
from app.services.etl import _consensus_attach as ca

EVENT = "evt-attach"
BEST_KEYS = {
    f"best_{k}"
    for k in ("book", "line", "price", "side", "fair_prob", "ev", "quoted_at")
}


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    OddsLineSnapshot.__table__.create(engine)
    NFLGameLines.__table__.create(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def seed(db, books, market, *, player=None, age=timedelta(0), event=EVENT):
    """books: {book: (point, a, b)}; a/b = over/home, under/away prices."""
    at = datetime.utcnow() - age
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
                        "last_update": at.isoformat() + "Z",
                        "outcomes": outcomes,
                    }
                ],
            }
        )
    payload = {
        "id": event,
        "commence_time": (datetime.utcnow() + timedelta(hours=4)).isoformat() + "Z",
        "home_team": "Home",
        "away_team": "Away",
        "bookmakers": out,
    }
    rows = snaps.parse_payload("americanfootball_nfl", payload)
    snaps.record_rows(db, rows, at)


# four books at one line, one book (williamhill_us) at another
SPREADS = {
    "fanduel": (-4.5, -110, -110),
    "draftkings": (-4.5, -110, -110),
    "betmgm": (-4.5, -112, -108),  # best away price (-108)
    "espnbet": (-4.5, -105, -115),  # best home price (-105)
    "williamhill_us": (-5.5, 100, -120),
}
TOTALS = {
    "fanduel": (45.5, -110, -110),
    "draftkings": (45.5, -110, -110),
    "betmgm": (45.5, -105, -115),  # best over
    "espnbet": (45.5, -115, -105),  # best under
    "williamhill_us": (46.5, 100, -120),
}
H2H = {
    "fanduel": (None, -200, 170),
    "draftkings": (None, -205, 175),
    "betmgm": (None, -200, 172),
    "espnbet": (None, -210, 180),  # best away price
    "williamhill_us": (None, -195, 165),  # best home price
}


ML_KEYS = {
    f"ml_best_{k}" for k in ("book", "price", "side", "fair_prob", "ev", "quoted_at")
}


def _all_none(fields, keys=BEST_KEYS):
    assert set(fields) == keys
    assert all(v is None for v in fields.values())


def test_spread_home_side_stores_home_line(db):
    seed(db, SPREADS, "spreads")
    f = ca.spread_fields(db, event_id=EVENT, margin=8.0, spread_home=-4.5)
    assert f["best_side"] == "home"
    assert f["best_book"] == "espnbet" and f["best_price"] == -105
    assert f["best_line"] == -4.5  # not the -5.5 book: no price travels across lines
    assert f["best_fair_prob"] is not None and f["best_ev"] is not None
    assert f["best_quoted_at"] is not None


def test_spread_away_side_stores_away_line_sign(db):
    seed(db, SPREADS, "spreads")
    f = ca.spread_fields(db, event_id=EVENT, margin=1.0, spread_home=-4.5)  # 1-4.5 < 0
    assert f["best_side"] == "away"
    assert f["best_book"] == "betmgm" and f["best_price"] == -108
    assert f["best_line"] == 4.5  # away line = -(home point)
    assert f["best_fair_prob"] is not None


def test_spread_on_the_line_has_no_side(db):
    seed(db, SPREADS, "spreads")
    _all_none(ca.spread_fields(db, event_id=EVENT, margin=4.5, spread_home=-4.5))


def test_moneyline_prefix_and_side(db):
    seed(db, H2H, "h2h")
    # market margin = -spread_home = 4.5; projection above it -> home
    f = ca.moneyline_fields(db, event_id=EVENT, margin=6.0, spread_home=-4.5)
    assert set(f) == {
        f"ml_best_{k}"
        for k in ("book", "price", "side", "fair_prob", "ev", "quoted_at")
    }
    assert f["ml_best_side"] == "home" and f["ml_best_book"] == "williamhill_us"
    assert f["ml_best_price"] == -195 and f["ml_best_fair_prob"] is not None
    away = ca.moneyline_fields(db, event_id=EVENT, margin=2.0, spread_home=-4.5)
    assert away["ml_best_side"] == "away" and away["ml_best_book"] == "espnbet"
    assert away["ml_best_price"] == 180


def test_moneyline_without_spread_is_none(db):
    seed(db, H2H, "h2h")
    f = ca.moneyline_fields(db, event_id=EVENT, margin=2.0, spread_home=None)
    assert all(v is None for v in f.values())


def test_total_over_and_under(db):
    seed(db, TOTALS, "totals")
    over = ca.line_fields(
        db, event_id=EVENT, market="totals", projection=48.0, line=45.5
    )
    assert over["best_side"] == "over" and over["best_book"] == "betmgm"
    assert over["best_line"] == 45.5 and over["best_fair_prob"] is not None
    under = ca.line_fields(
        db, event_id=EVENT, market="totals", projection=43.0, line=45.5
    )
    assert under["best_side"] == "under" and under["best_book"] == "espnbet"
    assert under["best_line"] == 45.5


def test_player_prop_matches_the_player(db):
    props = {
        b: (250.5, a, u) for b, (_, a, u) in TOTALS.items() if b != "williamhill_us"
    }
    props["williamhill_us"] = (260.5, 100, -120)
    seed(db, props, "player_pass_yds", player="Josh Allen")
    seed(db, props, "player_pass_yds", player="Other Guy")
    f = ca.line_fields(
        db,
        event_id=EVENT,
        market="player_pass_yds",
        projection=270.0,
        line=250.5,
        player="Josh Allen",
    )
    assert f["best_side"] == "over" and f["best_line"] == 250.5
    assert f["best_book"] == "betmgm" and f["best_fair_prob"] is not None


@pytest.mark.parametrize("age", [timedelta(minutes=45), timedelta(hours=3)])
def test_stale_snapshots_give_all_none(db, age):
    seed(db, SPREADS, "spreads", age=age)
    seed(db, H2H, "h2h", age=age)
    seed(db, TOTALS, "totals", age=age)
    _all_none(ca.spread_fields(db, event_id=EVENT, margin=8.0, spread_home=-4.5))
    _all_none(
        ca.moneyline_fields(db, event_id=EVENT, margin=8.0, spread_home=-4.5), ML_KEYS
    )
    _all_none(
        ca.line_fields(db, event_id=EVENT, market="totals", projection=50, line=45.5)
    )


def test_missing_event_or_inputs_give_all_none(db):
    seed(db, TOTALS, "totals")
    for kw in (
        dict(event_id=None, projection=50, line=45.5),
        dict(event_id=EVENT, projection=None, line=45.5),
        dict(event_id=EVENT, projection=50, line=None),
        dict(event_id=EVENT, projection=45.5, line=45.5),
    ):
        _all_none(ca.line_fields(db, market="totals", **kw))


def test_nfl_prop_fields_survives_a_row_without_teams(db):
    seed(db, TOTALS, "player_pass_yds", player="X")
    row = SimpleNamespace(game_date=datetime.utcnow())  # no team_name
    _all_none(
        ca.nfl_prop_fields(
            db, row, market="player_pass_yds", projection=1, line=2, player="X"
        )
    )


def test_nfl_prop_fields_finds_the_event_from_game_lines(db):
    day = (datetime.utcnow() + timedelta(hours=4)).date()
    db.add(
        NFLGameLines(
            game_date=day,
            home_team_id=1,
            away_team_id=2,
            home_team_name="Buffalo Bills",
            away_team_name="Miami Dolphins",
            odds_api_event_id=EVENT,
        )
    )
    db.commit()
    props = {
        b: (250.5, a, u) for b, (_, a, u) in TOTALS.items() if b != "williamhill_us"
    }
    seed(db, props, "player_pass_yds", player="Josh Allen")
    row = SimpleNamespace(
        game_date=datetime.combine(day, datetime.min.time()),
        team_name="Buffalo Bills",
        opponent_team_name="Miami Dolphins",
    )
    f = ca.nfl_prop_fields(
        db,
        row,
        market="player_pass_yds",
        projection=240.0,
        line=250.5,
        player="Josh Allen",
    )
    assert f["best_side"] == "under" and f["best_book"] == "espnbet"
    assert f["best_fair_prob"] is not None
