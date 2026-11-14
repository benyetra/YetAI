"""NHL keys must prove in: no auto pick and no board pick label without a qualifying
record (min_picks graded calls at or above breakeven), with the global
AUTO_PICK_REQUIRE_PROVEN_RECORD switch left off."""

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
        "AUTO_PICK_RECORD_PRIOR_MAX_PICKS",
        "AUTO_PICK_RECORD_SHRINK_PICKS",
    ):
        monkeypatch.delenv(k, raising=False)


def test_nhl_keys_need_a_qualifying_record_with_global_switch_off():
    assert not rg.require_proven_record()
    assert rg.drop_reason(None, SAVES) == "unproven_record"
    assert rg.drop_reason(None, TOTAL) == "unproven_record"
    # Thin record.
    assert rg.drop_reason(combine(SAVES, proj_n=10, proj_hits=8)) == "unproven_record"
    # Enough calls but below breakeven (inside the losing dead band).
    assert rg.drop_reason(combine(SAVES, proj_n=60, proj_hits=31)) == "unproven_record"
    # Losing record keeps its own reason.
    assert rg.drop_reason(combine(TOTAL, proj_n=60, proj_hits=20)) == "losing_record"
    # Enough calls at or above breakeven.
    assert rg.drop_reason(combine(SAVES, proj_n=60, proj_hits=34)) is None
    # Other leagues are unchanged: no data stays open.
    assert rg.drop_reason(None, POINTS) is None
    assert rg.drop_reason(combine(POINTS, proj_n=10, proj_hits=6)) is None


def test_prove_in_keys_switch(monkeypatch):
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
    assert rows["NHL/player_prop/saves"]["state"] == "WITHHELD unproven (prove-in key)"
    assert rows["NBA/moneyline"]["state"].startswith("unproven (would be")


def _seed_totals(db, n, hits, day):
    """n graded NHL totals OVER 5.5 calls on ``day``; ``hits`` of them go over."""
    for i in range(n):
        db.add(
            NHLTeamTotalsPredictions(
                game_date=day,
                home_team_id=100 + i,
                home_team_name=f"H{i}",
                away_team_id=200 + i,
                away_team_name=f"A{i}",
                predicted_home_goals=3.5,
                predicted_away_goals=3.0,
                predicted_total_goals=6.5,
                suggested_ou_line=6.5,
                draftkings_ou_line=5.5,
                edge=1.0,
                betting_recommendation="OVER 5.5",
            )
        )
        goals = 7 if i < hits else 4
        db.add(
            NHLTeamTotalsActuals(
                game_id=10_000 + i,
                game_date=day,
                home_team_id=100 + i,
                home_team_name=f"H{i}",
                away_team_id=200 + i,
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
        _board_payload(), sqlite_db, api._NHL_MARKET_KEYS
    )
    for group in ("goalie_predictions", "player_shots", "team_totals"):
        (row,) = out[group]
        assert row["betting_recommendation"] is None
        assert row["recommendation"] is None
        assert row["value_tier"] is None
        assert row["pick_withheld"] == "unproven_record"
        assert row["id"]  # the projection row itself stays


def test_board_keeps_pick_labels_once_the_record_qualifies(sqlite_db):
    yesterday = (datetime.utcnow() - timedelta(days=2)).date()
    _seed_totals(sqlite_db, 60, 36, yesterday)
    out = api._withhold_unproven_picks(
        _board_payload(), sqlite_db, api._NHL_MARKET_KEYS
    )
    assert out["team_totals"][0]["betting_recommendation"] == "OVER 5.5"
    assert "pick_withheld" not in out["team_totals"][0]
    assert out["goalie_predictions"][0]["value_tier"] is None


def test_board_strips_when_the_record_is_losing(sqlite_db):
    _seed_totals(sqlite_db, 60, 20, (datetime.utcnow() - timedelta(days=2)).date())
    out = api._withhold_unproven_picks(
        _board_payload(), sqlite_db, api._NHL_MARKET_KEYS
    )
    assert out["team_totals"][0]["betting_recommendation"] is None
    assert out["team_totals"][0]["pick_withheld"] == "losing_record"


def test_board_withholds_every_label_when_the_record_cannot_load(
    sqlite_db, monkeypatch
):
    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(rg, "load_records", boom)
    out = api._withhold_unproven_picks(
        _board_payload(), sqlite_db, api._NHL_MARKET_KEYS
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
    called = []
    monkeypatch.setattr(
        api, "_withhold_unproven_picks", lambda *a, **k: called.append(1) or a[0]
    )
    monkeypatch.setattr(api, "_merge_past_results", lambda p, *a: p)
    api.nhl_predictions(target_date=date(2026, 1, 1), **kw)
    assert called == []
