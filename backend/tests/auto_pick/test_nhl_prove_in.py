"""NHL keys must prove in: no auto pick and no board pick label without a qualifying
record (100 priced calls at or above breakeven), with the global
AUTO_PICK_REQUIRE_PROVEN_RECORD switch off. NHL saves and totals rows are valued at the
best consensus quote (best_line / best_price); rows without one (and every shots row) are
``unpriced_n`` only."""

from datetime import date, datetime, timedelta

import pytest

from app.api.v1 import predictions as api
from app.models.predictions_models import (
    NHLTeamTotalsActuals,
    NHLTeamTotalsPredictions,
)
from app.services.auto_pick import record_gate as rg
from app.services.auto_pick.orchestrator import AutoPickOrchestrator
from app.services.auto_pick.record_gate import combine
from tests.auto_pick.test_orchestrator import NOW, _cand

SAVES = ("NHL", "player_prop", "saves")
TOTAL = ("NHL", "total", None)
POINTS = ("NBA", "player_prop", "points")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in (
        "AUTO_PICK_RECORD_GATE_ENABLED",
        "AUTO_PICK_REQUIRE_PROVEN_RECORD",
        "AUTO_PICK_PROVE_IN_KEYS",
        "AUTO_PICK_RECORD_MIN_PICKS",
        "AUTO_PICK_RECORD_WINDOW_DAYS",
        "AUTO_PICK_RECORD_MIN_ROI",
        "AUTO_PICK_RECORD_SHRINK_PICKS",
    ):
        monkeypatch.delenv(k, raising=False)


def test_nhl_keys_need_a_qualifying_record_with_global_switch_off(monkeypatch):
    monkeypatch.setenv("AUTO_PICK_REQUIRE_PROVEN_RECORD", "false")
    assert not rg.require_proven_record()
    assert rg.drop_reason(None, SAVES) == "unproven_record"
    assert rg.drop_reason(None, TOTAL) == "unproven_record"

    def rec(key, n, hits, units):
        return combine(key, proj_n=n, proj_hits=hits, proj_units=units, dates=10)

    # Thin record.
    assert rg.drop_reason(rec(SAVES, 10, 8, 5.0)) == "unproven_record"
    # Enough calls but below breakeven (inside the losing dead band).
    assert rg.drop_reason(rec(SAVES, 100, 52, -2.0)) == "unproven_record"
    # Losing record keeps its own reason.
    assert rg.drop_reason(rec(TOTAL, 60, 20, -25.0)) == "losing_record"
    # 100 priced calls at or above breakeven.
    assert rg.drop_reason(rec(SAVES, 100, 58, 8.0)) is None
    # Other leagues are unchanged: no data stays open with the switch off.
    assert rg.drop_reason(None, POINTS) is None
    assert rg.drop_reason(rec(POINTS, 10, 6, 1.0)) is None


def test_prove_in_keys_switch(monkeypatch):
    monkeypatch.setenv("AUTO_PICK_REQUIRE_PROVEN_RECORD", "false")
    monkeypatch.setenv("AUTO_PICK_PROVE_IN_KEYS", "")
    assert rg.drop_reason(None, SAVES) is None
    monkeypatch.setenv("AUTO_PICK_PROVE_IN_KEYS", "NHL/total, NBA/player_prop/points")
    assert rg.drop_reason(None, SAVES) is None
    assert rg.drop_reason(None, TOTAL) == "unproven_record"
    assert rg.drop_reason(None, POINTS) == "unproven_record"
    monkeypatch.setenv("AUTO_PICK_PROVE_IN_KEYS", "NH")  # prefix must be a whole part
    assert rg.drop_reason(None, SAVES) is None


def test_orchestrator_drops_nhl_candidate_and_reports_shadow(sqlite_db):
    from app.services.auto_pick.selector import SelectorConfig

    o = AutoPickOrchestrator(db=sqlite_db, providers=[], now=NOW)
    o._records = {}
    c = _cand(1, league="NHL")
    c.projection_metadata["stat"] = "saves"
    sc = type("S", (), {"candidate": c, "drop_reason": "unproven_record"})()
    assert o._gate(sc, SelectorConfig(), set()) == "unproven_record"
    withheld = o._summarize_drops([], {})["withheld_keys"]
    assert withheld == {}
    sc.score = type("T", (), {"total": 80.0})()
    summary = o._summarize_drops([sc], {})
    assert summary["counts"] == {"unproven_record": 1}
    assert summary["withheld_keys"]["NHL/player_prop/saves"]["reason"] == (
        "unproven_record"
    )
    assert summary["withheld_keys"]["NHL/player_prop/saves"]["prove_in"] is True


def test_gate_report_marks_nhl_as_prove_in(sqlite_db):
    rows = {r["key"]: r for r in rg.gate_report(sqlite_db, NOW)}
    assert rows["NHL/player_prop/saves"]["state"] == "withheld-unproven"
    assert rows["NHL/player_prop/saves"]["reason"] == "unproven_record"
    assert rows["NBA/moneyline"]["state"] == "withheld-unproven"


def _seed_totals(
    db, n, hits, day, model_version="heuristic-v2", over_odds=None, base=0, quote=False
):
    """n graded NHL totals OVER 5.5 calls on ``day``; ``hits`` of them go over."""
    for i in range(base, base + n):
        db.add(
            NHLTeamTotalsPredictions(
                game_date=day,
                home_team_id=1
                + i % 10,  # real NHL ids: the source names the teams from them
                home_team_name=f"H{i}",
                away_team_id=12 + i % 10,
                away_team_name=f"A{i}",
                predicted_home_goals=3.5,
                predicted_away_goals=3.0,
                predicted_total_goals=6.5,
                suggested_ou_line=6.5,
                draftkings_ou_line=5.5,
                edge=1.0,
                betting_recommendation="OVER 5.5",
                model_version=model_version,
                over_odds=over_odds,
                under_odds=-130 if over_odds is not None else None,
                # the consensus best quote the priced record needs
                **(
                    dict(
                        best_book="fanduel",
                        best_line=5.5,
                        best_price=over_odds,
                        best_side="over",
                        best_fair_prob=0.55,
                        best_ev=0.1,
                    )
                    if quote
                    else {}
                ),
            )
        )
        goals = 7 if i - base < hits else 4
        db.add(
            NHLTeamTotalsActuals(
                game_id=2026020000 + i,
                game_date=day,
                home_team_id=1
                + i % 10,  # real NHL ids: the source names the teams from them
                home_team_name=f"H{i}",
                away_team_id=12 + i % 10,
                away_team_name=f"A{i}",
                actual_home_goals=goals - 2,
                actual_away_goals=2,
                actual_total_goals=goals,
            )
        )
    db.commit()


def _board_payload():
    return {
        "goalie_predictions": [
            {"id": 1, "recommendation": "OVER", "value_tier": "strong"}
        ],
        "player_shots": [{"id": 2, "betting_recommendation": "OVER 2.5"}],
        "team_totals": [{"id": 3, "betting_recommendation": "OVER 5.5"}],
    }


def test_board_strips_pick_labels_for_markets_without_record(sqlite_db):
    out = api._withhold_unproven_picks(
        _board_payload(), sqlite_db, api._BOARD_MARKETS["nhl"]
    )
    for group in ("goalie_predictions", "player_shots", "team_totals"):
        (row,) = out[group]
        assert row.get("betting_recommendation") is None
        assert row["recommendation"] is None
        assert row.get("value_tier") is None
        # Shots have no gate key at all: withheld as never measured.
        want = "no_record_check" if group == "player_shots" else "unproven_record"
        assert row["pick_withheld"] == want
        assert row["id"]  # the projection row itself stays


def test_nhl_winning_record_is_unpriced_so_labels_stay_stripped(sqlite_db):
    # 60 winning NHL totals calls with stored odds but no best quote: counted for display
    # only, never valued.
    for d in range(6):
        day = (datetime.utcnow() - timedelta(days=2 + d)).date()
        _seed_totals(sqlite_db, 10, 6, day, over_odds=-110, base=100 * d)
    rec = rg.load_records(sqlite_db, datetime.utcnow())[TOTAL]
    assert (rec.unpriced_n, rec.n_eff, rec.version) == (60, 0, "heuristic-v2")
    out = api._withhold_unproven_picks(
        _board_payload(), sqlite_db, api._BOARD_MARKETS["nhl"]
    )
    assert out["team_totals"][0]["betting_recommendation"] is None
    assert out["team_totals"][0]["pick_withheld"] == "unproven_record"


def test_pre_repair_rows_do_not_count_toward_the_record(sqlite_db):
    # 60 winning calls from the old model (heuristic-v1): still no record.
    _seed_totals(
        sqlite_db,
        60,
        50,
        (datetime.utcnow() - timedelta(days=2)).date(),
        "heuristic-v1",
    )
    assert rg.load_records(sqlite_db, NOW)[TOTAL].unpriced_n == 0
    out = api._withhold_unproven_picks(
        _board_payload(), sqlite_db, api._BOARD_MARKETS["nhl"]
    )
    assert out["team_totals"][0]["pick_withheld"] == "unproven_record"


def test_board_withholds_every_label_when_the_record_cannot_load(
    sqlite_db, monkeypatch
):
    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(rg, "load_records", boom)
    out = api._withhold_unproven_picks(
        _board_payload(), sqlite_db, api._BOARD_MARKETS["nhl"]
    )
    assert out["team_totals"][0]["pick_withheld"] == "record_unavailable"
    assert out["team_totals"][0]["betting_recommendation"] is None


def test_live_board_endpoint_withholds_and_past_slate_does_not(sqlite_db, monkeypatch):
    today = api.eastern_today()
    sqlite_db.add(
        NHLTeamTotalsPredictions(
            game_date=today,
            home_team_id=1,
            home_team_name="H",
            away_team_id=2,
            away_team_name="A",
            predicted_home_goals=3.5,
            predicted_away_goals=3.0,
            predicted_total_goals=6.5,
            suggested_ou_line=6.5,
            draftkings_ou_line=5.5,
            betting_recommendation="OVER 5.5",
        )
    )
    sqlite_db.commit()
    kw = dict(tz="UTC", limit=50, _user={}, db=sqlite_db)
    live = api.nhl_predictions(target_date=today, **kw)
    assert live["team_totals"][0]["betting_recommendation"] is None
    # A past slate keeps the graded call of a past game...
    monkeypatch.setattr(api, "_merge_past_results", lambda p, *a: p)
    monkeypatch.setattr(api, "eastern_today", lambda: today + timedelta(days=1))
    past = api.nhl_predictions(target_date=today, **kw)
    assert past["team_totals"][0]["betting_recommendation"] == "OVER 5.5"


def test_nba_board_strips_labels_for_new_steals_and_blocks_lines(
    sqlite_db, monkeypatch
):
    # Prove-in keys only (require-proven off), so points shows the prove-in list's reach.
    monkeypatch.setenv("AUTO_PICK_REQUIRE_PROVEN_RECORD", "false")
    payload = {
        "steals": [{"id": 1, "recommendation": "OVER", "fanduel_over_under": "o"}],
        "blocks": [{"id": 2, "recommendation": "UNDER", "fanduel_over_under": "u"}],
        "points": [{"id": 3, "recommendation": "OVER", "fanduel_over_under": "o"}],
    }
    out = api._withhold_unproven_picks(
        payload, sqlite_db, api._BOARD_MARKETS["nba"], loaders=("nba_props",)
    )
    for group, why in (("steals", "unproven_record"), ("blocks", "no_record_check")):
        row = out[group][0]
        assert row["recommendation"] is None and row["fanduel_over_under"] is None
        assert row["pick_withheld"] == why
    assert out["points"][0]["recommendation"] == "OVER"  # not a new market: untouched
    # The merged default (require-proven on) withholds points too until it proves in.
    monkeypatch.delenv("AUTO_PICK_REQUIRE_PROVEN_RECORD")
    out = api._withhold_unproven_picks(
        payload, sqlite_db, api._BOARD_MARKETS["nba"], loaders=("nba_props",)
    )
    assert out["points"][0]["pick_withheld"] == "unproven_record"


def test_nhl_totals_with_stored_odds_build_a_priced_record(sqlite_db):
    # 12 slate dates x 10 calls at +100, 6 of 10 over each night: 120 priced calls, +24u.
    today = datetime.utcnow()
    for d in range(12):
        _seed_totals(
            sqlite_db,
            10,
            6,
            (today - timedelta(days=2 + d)).date(),
            over_odds=100,
            base=100 * d,
            quote=True,
        )
    _seed_totals(
        sqlite_db, 5, 5, (today - timedelta(days=20)).date(), base=5000, over_odds=100
    )
    rec = rg.load_records(sqlite_db, today, ("nhl",))[TOTAL]
    assert (rec.proj_n, rec.proj_hits, rec.dates) == (120, 72, 12)
    assert rec.proj_units == pytest.approx(24.0)  # at +100, never at an assumed -110
    assert rec.unpriced_n == 5  # rows without a best quote are counted, never valued
    assert rg.drop_reason(rec) is None  # proved in
    # ...and an NHL candidate still has no consensus price, so it is never picked.
    from app.services.auto_pick import ev

    c = _cand(1, league="NHL")
    c.projection_metadata.pop("fair_prob")
    assert ev.candidate_ev(c) == (None, "no_consensus_price")


def test_nhl_pick_price_is_the_picked_side(sqlite_db):
    from app.services.nhl_accuracy_service import _nhl_rows

    day = (datetime.utcnow() - timedelta(days=2)).date()
    _seed_totals(sqlite_db, 1, 1, day, over_odds=105)
    (row,) = _nhl_rows(sqlite_db, start=day, end=day)["team_totals"]
    assert (row["betting_pick"], row["pick_price"]) == ("over", 105)
