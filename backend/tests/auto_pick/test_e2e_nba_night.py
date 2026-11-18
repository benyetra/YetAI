"""One NBA night through the merged system, on sqlite.

priced prop rows with a consensus fair prob -> the selector under prove-in with an unproven
record writes no bet and the board shows no pick -> a proven priced record is seeded -> the
selector picks only +EV, fresh, non-low-sample rows, ranked by EV, under the per-market cap ->
the board shows a pick only for that open market -> the review's gate table and bets record
report it.
"""

from datetime import date, datetime, timedelta

import pytest

from app.api.v1 import predictions as api
from app.models.database_models import AutoPickRun, BetSource, YetAIBet
from app.models.predictions_models import NBAGameLines, PointsActuals, PointsProjections
from app.services import model_review_service as review
from app.services.auto_pick import ev
from app.services.auto_pick.orchestrator import AutoPickOrchestrator
from app.tasks.auto_pick import _build_providers
from tests.test_model_review_yardsticks import _empty_review as _empty

DAY = date(2026, 11, 18)  # EST: ET = UTC - 5
NOW = datetime(
    2026, 11, 18, 18, 30
)  # 13:30 ET, the morning run; 12:00 ET refresh = 17:00 UTC
FRESH = datetime(2026, 11, 18, 17, 10)  # written by the 12:00 ET refresh
STALE = datetime(2026, 11, 18, 15, 0)  # 10:00 ET: before the 12:00 refresh
TIP = datetime(2026, 11, 19, 0, 0)  # 19:00 ET
VERSION = "xgb-11-14"

# player id -> (opponent, projection, best line, best price, fair prob, projected_at, low)
TONIGHT = {
    1: ("Opp1", 30.0, 24.5, 100, 0.52, FRESH, None),  # +EV, best
    2: ("Opp2", 27.0, 24.5, -105, 0.52, FRESH, None),  # +EV, second
    3: ("Opp3", 25.5, 24.5, -104, 0.52, FRESH, False),  # +EV, third: market cap is 2
    4: ("Opp4", 30.0, 24.5, -110, 0.45, FRESH, None),  # negative consensus EV
    5: ("Opp5", 30.0, 24.5, 100, 0.52, STALE, None),  # +EV but stale
    6: ("Opp6", 30.0, 24.5, 100, 0.52, FRESH, True),  # +EV but low sample
}


def _game(db, n):
    db.add(
        NBAGameLines(
            game_date=DAY,
            home_team_name=f"Home{n}",
            away_team_name=f"Opp{n}",
            game_time=TIP,
            odds_api_event_id=f"ev{n}",
        )
    )


def _prop(db, pid, day, opp, proj, line, price, fair, at, low=None):
    db.add(
        PointsProjections(
            date=day,
            player_id=pid,
            player_name=f"P{pid}",
            opponent_team_name=opp,
            projected_points=proj,
            fanduel_line=line,
            fanduel_over_under="o",
            fanduel_price=price,
            best_book="dk",
            best_line=line,
            best_price=price,
            best_fair_prob=fair,
            best_quoted_at=at,
            projected_at=at,
            low_sample=low,
            model_version=VERSION,
        )
    )


def _seed_tonight(db):
    for n in range(1, 7):
        _game(db, n)
    for pid, (opp, proj, line, price, fair, at, low) in TONIGHT.items():
        _prop(db, pid, DAY, opp, proj, line, price, fair, at, low)
    db.commit()


def _seed_proven_record(db):
    """12 slate dates x 10 priced over calls at +100, 6 of 10 over: +24u on 120 calls."""
    for d in range(1, 13):
        day = DAY - timedelta(days=d)
        for i in range(10):
            pid = 1000 + 100 * d + i
            _prop(db, pid, day, "OppX", 30.0, 24.5, 100, 0.52, datetime(2026, 1, 1))
            db.add(
                PointsActuals(
                    date=day,
                    player_id=pid,
                    actual_points=28.0 if i < 6 else 20.0,
                    projected_points=30.0,
                )
            )
    db.commit()


async def _run(db):
    return await AutoPickOrchestrator(
        db=db, providers=_build_providers(db), now=NOW, reserve_slots=0
    ).run()


def _board(db):
    payload = {
        "points": [
            {"id": pid, "player_id": pid, "recommendation": "OVER", "edge": 5.5}
            for pid in TONIGHT
        ],
        "assists": [{"id": 9, "recommendation": "OVER", "edge": 1.0}],
    }
    return api._withhold_board_picks(payload, db, "nba", None)


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


@pytest.mark.asyncio
async def test_one_nba_night_through_gate_selector_board_and_review(sqlite_db):
    db = sqlite_db
    _seed_tonight(db)

    # 1. Unproven record: no bet, no board pick.
    result = await _run(db)
    assert result.pick_count == 0 and db.query(YetAIBet).count() == 0
    run = db.query(AutoPickRun).one()
    assert run.dropped_reasons["withheld_keys"]["NBA/player_prop/points"]["reason"] == (
        "unproven_record"
    )
    board = _board(db)
    assert all(r["recommendation"] is None for r in board["points"])
    assert all(r["pick_withheld"] == "unproven_record" for r in board["points"])

    # 2. A proven priced record on the current model version opens points only.
    _seed_proven_record(db)
    result = await _run(db)
    bets = db.query(YetAIBet).filter(YetAIBet.source == BetSource.AUTO).all()
    picked = sorted(
        bets, key=lambda b: -b.prediction_factors["ev"]["ev"]  # ranked by EV
    )
    players = [b.prediction_factors["projection_metadata"]["player"] for b in picked]
    # Only +EV, fresh, non-low-sample rows; the third +EV row loses to the market cap.
    assert players == ["P1", "P2"], players
    assert all(
        b.prediction_factors["selection_version"] == ev.SELECTION_VERSION for b in bets
    )
    assert all(b.prediction_factors["ev"]["ev"] > ev.MIN_EV for b in bets)
    counts = db.query(AutoPickRun).order_by(AutoPickRun.id.desc()).first()
    reasons = counts.dropped_reasons["counts"]
    assert reasons.get("negative_consensus_ev") == 1, reasons
    assert reasons.get("stale_line") == 1, reasons
    # P3 passed every gate and lost only to the cap; P6 (low sample) was never a candidate.
    assert sum(reasons.values()) == 3 and counts.candidates_considered == 5, reasons

    # 3. The board shows a pick for the open market only.
    board = _board(db)
    assert all(r["recommendation"] == "OVER" for r in board["points"])
    assert "pick_withheld" not in board["points"][0]
    assert board["assists"][0]["pick_withheld"] == "unproven_record"
    assert board["assists"][0]["edge"] is None

    # 4. Next day: the bets settle; the review's gate table and bets record report it.
    for b in bets:
        b.status, b.settled_at = "won", datetime(2026, 11, 19, 5, 0)
    db.commit()
    gate = review._gate_section(db, DAY + timedelta(days=1))
    points = {k["key"]: k for k in gate["keys"]}["NBA/player_prop/points"]
    assert (points["state"], points["version"]) == ("open", VERSION)
    assert points["n"] >= 120 and points["dates"] >= 12
    assert points["selection_version"] == ev.SELECTION_VERSION
    text = review.render_text(
        {
            **_empty(),
            "gate": gate,
            "bets": review._bets_section(db, DAY + timedelta(days=1)),
        }
    )
    assert "NBA/player_prop/points | open |" in text
    record = review._bets_section(db, DAY + timedelta(days=1))["windows"]["7"]
    assert (record["picks"], record["w"]) == (2, 2)
