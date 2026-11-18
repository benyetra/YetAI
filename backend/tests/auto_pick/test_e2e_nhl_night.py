"""One NHL night through the merged system, on sqlite.

Same shape as the NFL Sunday: lines are seeded as Odds API snapshots, best_* is written by the
real attach code the NHL writer uses (``etl._consensus_attach.line_fields``) at the time the
row was "written"; goalie saves and team totals are unproven (no bet, board stripped) until a
proven priced record is seeded; then the 18:00 ET run picks only fresh, +EV rows (16:45 ET
refresh), under the caps; a 22:00 ET game written only by the 05:00 ET run is stale.
"""

from datetime import date, datetime, timedelta

import pytest

from app.api.v1 import predictions as api
from app.models.database_models import AutoPickRun, YetAIBet
from app.models.predictions_models import (
    NHLGoalieActuals,
    NHLGoaliePredictions,
    NHLTeamTotalsActuals,
    NHLTeamTotalsPredictions,
)
from app.services import model_review_service as review
from app.services import odds_snapshots as snaps
from app.services.auto_pick import ev
from app.services.auto_pick.orchestrator import AutoPickOrchestrator
from app.services.etl._consensus_attach import line_fields
from app.tasks.auto_pick import _build_providers
from tests.test_model_review_yardsticks import _empty_review as _empty

DAY = date(2026, 11, 18)  # EST: ET = UTC - 5
NOW = datetime(2026, 11, 18, 23, 0)  # 18:00 ET
FRESH = datetime(2026, 11, 18, 21, 50)  # written by the 16:45 ET refresh (21:45 UTC)
STALE = datetime(2026, 11, 18, 10, 0)  # 05:00 ET pipeline, before the 16:45 refresh
VERSION = "heuristic-v2"
BOOKS = ("fanduel", "draftkings", "betmgm", "williamhill_us")


def _books(line, outlier):
    """Four books at one line at -110/-110 plus one outlier over price (the best quote)."""
    out = {b: (line, -110, -110) for b in BOOKS}
    out["espnbet"] = (line, outlier, -110 - (outlier - 100))
    return out


# game -> (home id, away id, kickoff ET hour, over price at the outlier book, write time,
#          snapshot time). Every game has one goalie and one total on the same prices.
GAMES = {
    1: (6, 10, 19, 112, FRESH, FRESH - timedelta(minutes=4)),  # best EV
    2: (1, 3, 19, 108, FRESH, FRESH - timedelta(minutes=4)),
    3: (4, 5, 19, 106, FRESH, FRESH - timedelta(minutes=4)),  # +EV, loses to the caps
    4: (7, 8, 19, -110, FRESH, FRESH - timedelta(minutes=4)),  # nothing above fair
    5: (12, 13, 22, 112, STALE, STALE - timedelta(minutes=2)),  # 22:00 ET, 05:00 write
    6: (14, 15, 19, 112, FRESH, datetime(2026, 11, 18, 21, 0)),  # capture refused
}


def _kickoff_utc(hour):
    return datetime.combine(DAY, datetime.min.time()) + timedelta(hours=hour + 5)


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
    snaps.record_rows(db, snaps.parse_payload("icehockey_nhl", payload), at)


def _seed_night(db):
    for n, (home, away, hour, price, wrote, seen) in GAMES.items():
        event, kick = f"nhl-ev{n}", _kickoff_utc(hour)
        goalie = f"Goalie {n}"
        _snapshot(db, event, _books(5.5, price), "totals", seen, kick)
        _snapshot(
            db, event, _books(27.5, price), "player_total_saves", seen, kick, goalie
        )
        at_et = datetime.combine(DAY, datetime.min.time()) + timedelta(hours=hour)
        db.add(
            NHLGoaliePredictions(
                game_date=DAY,
                goalie_id=n,
                goalie_name=goalie,
                team_id=home,
                team_name="Home",
                opponent_team_id=away,
                opponent_team_name="Away",
                is_home=True,
                game_time=at_et,
                starter_confirmed=True,
                was_scratch=False,
                predicted_saves=30.0,
                predicted_shots_against=32.0,
                predicted_save_pct=0.92,
                saves_line=27.5,
                over_odds=-110,
                under_odds=-110,
                model_version=VERSION,
                prediction_date=wrote,
                # the writer's own attach call
                **line_fields(
                    db,
                    event_id=event,
                    market="player_total_saves",
                    projection=30.0,
                    line=27.5,
                    player=goalie,
                    now=wrote,
                ),
            )
        )
        db.add(
            NHLTeamTotalsPredictions(
                game_date=DAY,
                game_time_et=at_et,
                home_team_id=home,
                home_team_name="Home",
                away_team_id=away,
                away_team_name="Away",
                predicted_home_goals=3.5,
                predicted_away_goals=3.0,
                predicted_total_goals=6.5,
                suggested_ou_line=6.5,
                draftkings_ou_line=5.5,
                over_odds=-110,
                under_odds=-110,
                model_version=VERSION,
                prediction_date=wrote,
                **line_fields(
                    db,
                    event_id=event,
                    market="totals",
                    projection=6.5,
                    line=5.5,
                    now=wrote,
                ),
            )
        )
    db.commit()


def _quote(line, price=-110, fair=0.55):
    return {
        "best_book": "fanduel",
        "best_line": line,
        "best_price": price,
        "best_side": "over",
        "best_fair_prob": fair,
        "best_ev": 0.05,
        "best_quoted_at": datetime(2026, 1, 1),
    }


def _seed_proven_record(db):
    """100 graded over calls (saves and totals) on 20 past dates, 3 of 5 win, at -110."""
    for d in range(1, 21):
        day = date(2026, 11, 17) - timedelta(days=d)
        for i in range(5):
            hit = i < 3
            home, away = (1, 3, 4, 7, 12)[i], (2, 5, 8, 9, 13)[i]
            at = datetime.combine(day, datetime.min.time()) + timedelta(hours=19)
            db.add(
                NHLGoaliePredictions(
                    game_date=day,
                    goalie_id=1000 * d + i,
                    goalie_name="G",
                    team_id=home,
                    team_name="Home",
                    opponent_team_id=away,
                    opponent_team_name="Away",
                    is_home=True,
                    game_time=at,
                    starter_confirmed=True,
                    was_scratch=False,
                    predicted_saves=30.0,
                    predicted_shots_against=32.0,
                    predicted_save_pct=0.92,
                    saves_line=27.5,
                    over_odds=-110,
                    under_odds=-110,
                    model_version=VERSION,
                    prediction_date=at,
                    **_quote(27.5),
                )
            )
            db.add(
                NHLGoalieActuals(
                    game_id=2026020000 + 100 * d + i,
                    game_date=day,
                    goalie_id=1000 * d + i,
                    goalie_name="G",
                    team_name="Home",
                    opponent_team_name="Away",
                    actual_saves=30 if hit else 20,
                    actual_shots_against=32,
                    actual_save_pct=0.9,
                    actual_goals_against=2,
                )
            )
            db.add(
                NHLTeamTotalsPredictions(
                    game_date=day,
                    game_time_et=at,
                    home_team_id=home,
                    home_team_name="Home",
                    away_team_id=away,
                    away_team_name="Away",
                    predicted_home_goals=3.5,
                    predicted_away_goals=3.0,
                    predicted_total_goals=6.5,
                    suggested_ou_line=6.5,
                    draftkings_ou_line=5.5,
                    over_odds=-110,
                    under_odds=-110,
                    model_version=VERSION,
                    prediction_date=at,
                    **_quote(5.5),
                )
            )
            db.add(
                NHLTeamTotalsActuals(
                    game_id=2026021000 + 100 * d + i,
                    game_date=day,
                    home_team_id=home,
                    home_team_name="Home",
                    away_team_id=away,
                    away_team_name="Away",
                    actual_home_goals=4 if hit else 2,
                    actual_away_goals=3 if hit else 2,
                    actual_total_goals=7 if hit else 4,
                )
            )
    db.commit()


async def _run(db, monkeypatch, dry_run=False):
    """Run the orchestrator at NOW; also returns every candidate's drop reason (None =
    kept), keyed (home team id's full name, market)."""
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
        "recommendation": "OVER",
        "edge": 2.0,
        "best_side": "over",
        "best_price": 112,
    }
    payload = {
        "goalie_predictions": [dict(row)],
        # the real stored row of the picked game: the board asks the selector's own gates
        "team_totals": [
            api._row_to_dict(
                db.query(NHLTeamTotalsPredictions)
                .filter(NHLTeamTotalsPredictions.home_team_id == 6)
                .one()
            )
        ],
        "player_shots": [{"recommendation": "OVER", "edge": 1.0}],
    }
    return api._withhold_board_picks(payload, db, "nhl", None)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in (
        "AUTO_PICK_REQUIRE_PROVEN_RECORD",
        "AUTO_PICK_PROVE_IN_KEYS",
        "AUTO_PICK_RECORD_GATE_ENABLED",
        "AUTO_YETAI_PICKS_AUTO_PUBLISH",
        "NHL_GOALIE_PROBABLE_PICKS",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(api, "eastern_today", lambda: DAY)
    # The board reads the record at the wall clock; pin it to the run's clock.
    monkeypatch.setattr(
        api, "datetime", type("D", (datetime,), {"utcnow": staticmethod(lambda: NOW)})
    )


@pytest.mark.asyncio
async def test_one_nhl_night_through_gate_selector_board_and_review(
    sqlite_db, monkeypatch
):
    db = sqlite_db
    _seed_night(db)

    # The attach wrote a quote on the fresh and the stale rows, nothing where capture failed.
    goalies = {g.goalie_id: g for g in db.query(NHLGoaliePredictions).all()}
    assert goalies[1].best_book == "espnbet" and goalies[1].best_price == 112
    assert goalies[1].best_side == "over" and goalies[1].best_line == 27.5
    assert goalies[6].best_price is None  # only 50 minute old snapshots
    totals = {t.home_team_id: t for t in db.query(NHLTeamTotalsPredictions).all()}
    assert totals[6].best_side == "over" and totals[14].best_price is None

    # 1. Unproven record: no bet, the board strips every NHL pick field.
    result, _ = await _run(db, monkeypatch)
    assert result.pick_count == 0 and db.query(YetAIBet).count() == 0
    withheld = db.query(AutoPickRun).one().dropped_reasons["withheld_keys"]
    for key in ("NHL/player_prop/saves", "NHL/total"):
        assert withheld[key]["reason"] == "unproven_record", key
    board = _board(db)
    for group, reason in (
        ("goalie_predictions", "unproven_record"),
        ("team_totals", "unproven_record"),
        ("player_shots", "no_record_check"),  # shots are never auto-picked: no gate key
    ):
        (row,) = board[group]
        assert row["recommendation"] is None and row["edge"] is None, group
        assert row.get("best_side") is None and row["pick_withheld"] == reason, group

    # 2. A proven priced saves and totals record.
    _seed_proven_record(db)
    dry, why = await _run(db, monkeypatch, dry_run=True)
    assert db.query(YetAIBet).count() == 0 and dry.pick_count == 3
    total = {k[0]: v for k, v in why.items() if k[1] == "total"}
    saves = {k[0]: v for k, v in why.items() if k[1] == "player_prop"}
    assert total == {
        "Boston Bruins": None,  # fresh, +EV: picked
        "New Jersey Devils": None,  # picked
        "Philadelphia Flyers": "market_concentration",  # +EV too, 2 per league+market
        "Buffalo Sabres": "negative_consensus_ev",
        "Carolina Hurricanes": "stale_line",  # 22:00 ET game written by the 05:00 ET run
        "Tampa Bay Lightning": "no_consensus_price",  # capture refused
    }, total
    # One pick per game: the saves rows of games that already have their total are dropped;
    # the third game's saves row (its total lost to the cap) is the one saves pick.
    assert saves == {
        "Boston Bruins": "same_event",
        "New Jersey Devils": "same_event",
        "Philadelphia Flyers": None,
        "Buffalo Sabres": "negative_consensus_ev",
        "Carolina Hurricanes": "stale_line",
        "Tampa Bay Lightning": "no_consensus_price",
    }, saves

    await _run(db, monkeypatch)
    bets = db.query(YetAIBet).all()
    assert sorted((b.home_team, b.bet_type.value) for b in bets) == [
        ("Boston Bruins", "total"),
        ("New Jersey Devils", "total"),
        ("Philadelphia Flyers", "prop"),
    ]
    assert all(
        b.prediction_factors["selection_version"] == ev.SELECTION_VERSION for b in bets
    )
    assert all(b.prediction_factors["ev"]["ev"] > ev.MIN_EV for b in bets)
    assert sorted(b.odds for b in bets) == [106, 108, 112]  # the best book's price

    # 3. The board shows the NHL pick fields for the open markets; shots stay stripped.
    board = _board(db)
    for group in ("goalie_predictions", "team_totals"):
        (row,) = board[group]
        assert row["recommendation"] == "OVER" and row["best_side"] == "over", group
        assert "pick_withheld" not in row, group
    assert board["player_shots"][0]["recommendation"] is None

    # 4. The review's gate table lists the NHL keys with n / dates / unpriced.
    gate = review._gate_section(db, DAY + timedelta(days=1))
    keys = {k["key"]: k for k in gate["keys"]}
    for name in ("NHL/player_prop/saves", "NHL/total"):
        assert (keys[name]["state"], keys[name]["n"], keys[name]["dates"]) == (
            "open",
            100,
            20,
        )
        assert keys[name]["unpriced_n"] == 0 and keys[name]["version"] == VERSION
    assert keys["NHL/player_prop/shots"]["state"] == "withheld-unproven"
    text = review.render_text({**_empty(), "gate": gate})
    assert "NHL/total | open |" in text and "| dates | unpriced |" in text
