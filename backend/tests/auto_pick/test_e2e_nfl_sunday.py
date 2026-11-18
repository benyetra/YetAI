"""One NFL Sunday through the merged system, on sqlite.

Lines are seeded as Odds API snapshots (``odds_snapshots.record_rows``) and every best_* is
written by the real attach code the writers use (``etl/_consensus_attach``) at the time the
row was "written". Then: every key unproven -> no bet, the board strips every pick field ->
a proven priced NFL spread and moneyline record is seeded -> the 13:30 ET run picks only a
fresh, +EV row for a game that has not started, under the caps -> the board shows the open
markets only -> the review's gate table lists the keys.
"""

from datetime import date, datetime, timedelta

import pytest

from app.api.v1 import predictions as api
from app.models.database_models import AutoPickRun, YetAIBet
from app.models.predictions_models import (
    NFLGameLines,
    NFLSpreadActuals,
    NFLSpreadProjections,
    NFLTotalsProjections,
    QBPredictions,
    RecvYdsPredictions,
)
from app.services import model_review_service as review
from app.services import odds_snapshots as snaps
from app.services.auto_pick import ev
from app.services.auto_pick.orchestrator import AutoPickOrchestrator
from app.tasks.auto_pick import _build_providers
from tests.test_model_review_yardsticks import _empty_review as _empty
from app.services.etl import _consensus_attach as ca

DAY = date(2026, 11, 22)  # a Sunday; EST: ET = UTC - 5
NOW = datetime(2026, 11, 22, 18, 30)  # 13:30 ET
FRESH = datetime(2026, 11, 22, 17, 40)  # written by the 12:30 ET refresh (17:30 UTC)
STALE = datetime(2026, 11, 22, 15, 0)  # 10:00 ET: before the 12:30 refresh
LATE = datetime(2026, 11, 22, 21, 25)  # 16:25 ET kickoff
EARLY = datetime(2026, 11, 22, 18, 0)  # 13:00 ET kickoff: already started at 13:30
VERSION = "n1"
FACTORS = {"anchor": {"k": 0.3}, "model_margin": 9.0}

# four books at one line, the fifth (espnbet) is the outlier the best quote comes from
FLAT = {
    b: (-2.5, -110, -110) for b in ("fanduel", "draftkings", "betmgm", "williamhill_us")
}
SOFT = {**FLAT, "espnbet": (-2.5, 108, -128)}  # home +108: +EV against the other four
FAIR = {**FLAT, "espnbet": (-2.5, -110, -110)}  # nothing above fair: negative EV
ML_FLAT = {
    b: (None, -150, 130) for b in ("fanduel", "draftkings", "betmgm", "williamhill_us")
}
ML_SOFT = {**ML_FLAT, "espnbet": (None, -128, 108)}
TOTALS = {
    b: (47.5, -110, -110) for b in ("fanduel", "draftkings", "betmgm", "williamhill_us")
}
TOTALS = {**TOTALS, "espnbet": (47.5, 108, -128)}

# game -> (spread books, ml books, write time, snapshot time, kickoff)
GAMES = {
    1: (SOFT, ML_SOFT, FRESH, FRESH - timedelta(minutes=5), LATE),  # +EV spread and ML
    2: (SOFT, None, FRESH, FRESH - timedelta(minutes=5), LATE),  # +EV spread
    3: (SOFT, None, FRESH, FRESH - timedelta(minutes=5), LATE),  # +EV spread, cap of 2
    4: (FAIR, None, FRESH, FRESH - timedelta(minutes=5), LATE),  # negative consensus EV
    5: (SOFT, None, FRESH, FRESH - timedelta(minutes=5), EARLY),  # started at 13:30
    6: (SOFT, None, STALE, STALE - timedelta(minutes=5), LATE),  # written at 10:00 ET
    7: (SOFT, None, FRESH, datetime(2026, 11, 22, 16, 50), LATE),  # capture refused
}


def _team(n):
    return f"Home{n}", f"Away{n}"


def _snapshot(db, event, books, market, at, kickoff, player=None):
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
        "commence_time": kickoff.isoformat() + "Z",
        "home_team": "Home",
        "away_team": "Away",
        "bookmakers": out,
    }
    snaps.record_rows(db, snaps.parse_payload("americanfootball_nfl", payload), at)


def _seed_sunday(db):
    for n, (spread, ml, wrote, seen, kickoff) in GAMES.items():
        home, away = _team(n)
        event = f"nfl-ev{n}"
        _snapshot(db, event, spread, "spreads", seen, kickoff)
        if ml:
            _snapshot(db, event, ml, "h2h", seen, kickoff)
        db.add(
            NFLGameLines(
                game_date=DAY,
                home_team_name=home,
                away_team_name=away,
                odds_api_event_id=event,
                game_time=kickoff,
                spread_home=-2.5,
                spread_home_odds=-110,
                spread_away_odds=-110,
                total=47.5,
                over_odds=-110,
                under_odds=-110,
                moneyline_home=-150,
                moneyline_away=130,
            )
        )
        margin = 9.0 - 0.1 * n  # game 1 has the largest edge
        db.add(
            NFLSpreadProjections(
                game_date=DAY,
                home_team_name=home,
                away_team_name=away,
                projected_margin=margin,
                home_win_prob=0.7,
                market_spread_home=-2.5,
                recommendation="NO_PLAY",  # the EV rule decides, not this
                factors=FACTORS,
                model_version=VERSION,
                created_at=wrote,
                # the writers' own attach code, at the time the row was written
                **ca.spread_fields(
                    db, event_id=event, margin=margin, spread_home=-2.5, now=wrote
                ),
                **ca.moneyline_fields(
                    db, event_id=event, margin=margin, spread_home=-2.5, now=wrote
                ),
            )
        )
    # Game 1 also carries the other NFL markets, priced by the same attach code. They
    # have no record, so they stay unpicked and the board strips them.
    _snapshot(db, "nfl-ev1", TOTALS, "totals", FRESH - timedelta(minutes=5), LATE)
    _snapshot(
        db,
        "nfl-ev1",
        TOTALS,
        "player_pass_yds",
        FRESH - timedelta(minutes=5),
        LATE,
        "QB One",
    )
    home, away = _team(1)
    db.add(
        NFLTotalsProjections(
            game_date=DAY,
            home_team_name=home,
            away_team_name=away,
            projected_total=55.0,
            market_total=47.5,
            recommendation="NO_PLAY",
            model_version=VERSION,
            created_at=FRESH,
            **ca.line_fields(
                db,
                event_id="nfl-ev1",
                market="totals",
                projection=55.0,
                line=47.5,
                now=FRESH,
            ),
        )
    )
    db.add(
        QBPredictions(
            qb_player_id="q1",
            qb_player_name="QB One",
            team_id=1,
            venue_name="V",
            team_name=home,
            opponent_team_name=away,
            game_date=datetime.combine(DAY, datetime.min.time()) + timedelta(hours=16),
            season=2026,
            week=11,
            predicted_passing_yards=290.0,
            ou_line=47.5,
            over_odds=-110,
            under_odds=-110,
            model_version=VERSION,
            prediction_date=FRESH,
            # prop attach = nfl_prop_fields without its wall-clock default
            **ca.line_fields(
                db,
                event_id=ca.nfl_event_id(db, DAY, home, away),
                market="player_pass_yds",
                projection=290.0,
                line=47.5,
                player="QB One",
                now=FRESH,
            ),
        )
    )
    db.add(
        RecvYdsPredictions(
            season=2026,
            week=11,
            game_date=DAY,
            player_id="r1",
            player_name="WR One",
            position="WR",
            team_name=home,
            opponent_team_name=away,
            predicted_receiving_yards=80.0,
            ou_line=61.5,
            over_odds=-110,
            under_odds=-110,
            model_version=VERSION,
        )
    )
    db.commit()


def _seed_proven_record(db):
    """100 graded home calls on 10 past slate dates; both the spread (home -2.5 at -110,
    fair 0.55, 6 of 10 cover) and the moneyline (home at +120, fair 0.5, the home team
    always wins) are priced and positive."""
    for d in range(1, 11):
        day = date(2026, 11, 17) - timedelta(days=d)  # all before the real "today"
        for i in range(10):
            home, away = f"PH{d}-{i}", f"PA{d}-{i}"
            kw = dict(game_date=day, home_team_name=home, away_team_name=away)
            db.add(
                NFLGameLines(
                    odds_api_event_id=f"p{d}-{i}",
                    game_time=datetime.combine(day, datetime.min.time())
                    + timedelta(hours=18),
                    spread_home=-2.5,
                    spread_home_odds=-110,
                    spread_away_odds=-110,
                    moneyline_home=-150,
                    moneyline_away=130,
                    **kw,
                )
            )
            quote = {
                "best_book": "fanduel",
                "best_line": -2.5,
                "best_price": -110,
                "best_side": "home",
                "best_fair_prob": 0.55,
                "best_ev": 0.05,
                "best_quoted_at": datetime(2026, 1, 1),
                "ml_best_book": "fanduel",
                "ml_best_price": 120,
                "ml_best_side": "home",
                "ml_best_fair_prob": 0.5,
                "ml_best_ev": 0.1,
                "ml_best_quoted_at": datetime(2026, 1, 1),
            }
            db.add(
                NFLSpreadProjections(
                    projected_margin=8.0,
                    home_win_prob=0.7,
                    market_spread_home=-2.5,
                    recommendation="NO_PLAY",
                    factors=FACTORS,
                    model_version=VERSION,
                    created_at=datetime.combine(day, datetime.min.time()),
                    **kw,
                    **quote,
                )
            )
            margin = 10 if i < 6 else 1
            db.add(
                NFLSpreadActuals(
                    home_score=100 + margin,
                    away_score=100,
                    actual_margin=margin,
                    home_won=True,
                    **kw,
                )
            )
    db.commit()


async def _run(db, monkeypatch, dry_run=False):
    """Run the orchestrator at NOW; also returns every candidate's drop reason (None =
    kept), keyed (home team, market)."""
    seen = {}
    real = AutoPickOrchestrator._summarize_drops

    def spy(scored, records=None):
        for sc in scored:
            c = sc.candidate
            seen[(c.home_team, c.market_type.value)] = sc.drop_reason
        return real(scored, records)

    monkeypatch.setattr(AutoPickOrchestrator, "_summarize_drops", staticmethod(spy))
    result = await AutoPickOrchestrator(
        db=db,
        providers=_build_providers(db),
        now=NOW,
        reserve_slots=0,
        dry_run=dry_run,
    ).run()
    return result, seen


def _board(db):
    row = {
        "recommendation": "HOME",
        "edge": 5.5,
        "best_side": "home",
        "best_price": 108,
    }
    payload = {
        "spreads": [{**row, "ml_best_side": "home", "ml_best_price": 108}],
        "totals": [{**row, "best_side": "over"}],
        "qb_predictions": [{**row, "best_side": "over"}],
        "receiving_yards_predictions": [{**row, "best_side": "over"}],
    }
    return api._withhold_board_picks(payload, db, "nfl", None)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in (
        "AUTO_PICK_REQUIRE_PROVEN_RECORD",
        "AUTO_PICK_PROVE_IN_KEYS",
        "AUTO_PICK_RECORD_GATE_ENABLED",
        "AUTO_YETAI_PICKS_AUTO_PUBLISH",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(api, "eastern_today", lambda: DAY)
    # The board reads the record at the wall clock; pin it to the run's clock.
    monkeypatch.setattr(
        api, "datetime", type("D", (datetime,), {"utcnow": staticmethod(lambda: NOW)})
    )


@pytest.mark.asyncio
async def test_one_nfl_sunday_through_gate_selector_board_and_review(
    sqlite_db, monkeypatch
):
    db = sqlite_db
    _seed_sunday(db)

    # The attach wrote the consensus quote on the rows that had one, nothing on the rest.
    rows = {r.home_team_name: r for r in db.query(NFLSpreadProjections).all()}
    assert rows["Home1"].best_side == "home" and rows["Home1"].best_book == "espnbet"
    assert rows["Home1"].best_price == 108 and rows["Home1"].best_line == -2.5
    assert rows["Home1"].ml_best_side == "home"
    assert rows["Home2"].ml_best_price is None  # no h2h snapshots for that game
    assert rows["Home7"].best_price is None  # capture refused: only 50 min old quotes
    assert db.query(NFLTotalsProjections).one().best_side == "over"
    assert db.query(QBPredictions).one().best_side == "over"

    # 1. Every NFL key unproven: no bet, no board pick field.
    result, _ = await _run(db, monkeypatch)
    assert result.pick_count == 0 and db.query(YetAIBet).count() == 0
    withheld = db.query(AutoPickRun).one().dropped_reasons["withheld_keys"]
    for key in ("NFL/spread", "NFL/moneyline", "NFL/total"):
        assert withheld[key]["reason"] == "unproven_record", key
    board = _board(db)
    for group in ("spreads", "totals", "qb_predictions", "receiving_yards_predictions"):
        (row,) = board[group]
        assert row["recommendation"] is None and row["best_side"] is None, group
        assert row["best_price"] is None and row["pick_withheld"] == "unproven_record"
    assert board["spreads"][0]["ml_best_side"] is None

    # 2. A proven priced spread and moneyline record; a dry run, then the real run.
    _seed_proven_record(db)
    dry, why = await _run(db, monkeypatch, dry_run=True)
    assert db.query(YetAIBet).count() == 0 and dry.pick_count == 2
    spread = {k[0]: v for k, v in why.items() if k[1] == "spread"}
    assert spread == {
        "Home1": None,  # fresh, +EV, 16:25 kickoff: picked
        "Home2": None,  # picked
        "Home3": "market_concentration",  # +EV too, but 2 per league+market
        "Home4": "negative_consensus_ev",  # best price sits below the consensus fair price
        "Home5": "started_or_starting",  # 13:00 kickoff, run at 13:30
        "Home6": "stale_line",  # written at 10:00 ET, before the 12:30 refresh
        "Home7": "no_consensus_price",  # capture refused: only stale snapshots
    }, spread
    # One pick per game: Game 1's moneyline is also +EV but the game already has its spread.
    assert why[("Home1", "moneyline")] == "same_event"
    result, _ = await _run(db, monkeypatch)
    bets = db.query(YetAIBet).all()
    assert sorted(b.home_team for b in bets) == ["Home1", "Home2"]
    assert all(
        b.prediction_factors["selection_version"] == ev.SELECTION_VERSION for b in bets
    )
    assert all(b.prediction_factors["ev"]["ev"] > ev.MIN_EV for b in bets)
    assert all(b.odds == 108 for b in bets)  # the consensus best book's price

    # 3. The board shows the NFL pick fields for the open markets and strips the rest.
    board = _board(db)
    (spreads,) = board["spreads"]
    assert spreads["recommendation"] == "HOME" and spreads["best_side"] == "home"
    assert spreads["ml_best_side"] == "home" and "pick_withheld" not in spreads
    for group in ("totals", "qb_predictions", "receiving_yards_predictions"):
        (row,) = board[group]
        assert row["recommendation"] is None and row["best_side"] is None, group
        assert row["pick_withheld"] == "unproven_record", group

    # 4. The review's gate table lists the NFL keys with n / dates / unpriced.
    gate = review._gate_section(db, DAY + timedelta(days=1))
    keys = {k["key"]: k for k in gate["keys"]}
    for name in ("NFL/spread", "NFL/moneyline"):
        assert (keys[name]["state"], keys[name]["n"], keys[name]["dates"]) == (
            "open",
            100,
            10,
        )
        assert keys[name]["unpriced_n"] == 0 and keys[name]["version"] == VERSION
    for name in ("NFL/total", "NFL/player_prop/passing_yards"):
        assert keys[name]["state"] == "withheld-unproven" and keys[name]["n"] == 0
    text = review.render_text({**_empty(), "gate": gate})
    assert "NFL/spread | open |" in text and "| dates | unpriced |" in text
