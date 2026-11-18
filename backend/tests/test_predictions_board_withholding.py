"""One rule for every live board: a market the record gate withholds (or never
measures) carries no pick, side, strength or edge; projections and lines stay."""

from datetime import date, datetime

import pytest

from app.api.v1 import predictions as api
from app.models.predictions_models import (
    KickerPredictions,
    NFLAnytimeTDPredictions,
    NHLTeamTotalsPredictions,
)
from app.services.auto_pick import record_gate as rg
from tests.auto_pick.conftest import sqlite_db  # noqa: F401

ENDPOINTS = {
    "nba": api.nba_predictions,
    "nfl": api.nfl_predictions,
    "nhl": api.nhl_predictions,
    "mlb": api.mlb_predictions,
    "wnba": api.wnba_predictions,
}
PICKY = {
    "id": 1,
    "projected_value": 24.5,
    "fanduel_line": 22.5,
    "recommendation": "OVER",
    "betting_recommendation": "OVER 22.5",
    "fanduel_over_under": "o",
    "edge": 2.0,
    "edge_percentage": 9.0,
    "confidence_score": 80.0,
    "pick_confidence": 80.0,
    "value_tier": "strong",
    "best_book": "fanduel",
    "best_line": -3.5,
    "best_price": -105,
    "best_side": "home",
    "ml_best_book": "fanduel",
    "ml_best_price": -140,
    "ml_best_side": "home",
    "ml_best_fair_prob": 0.58,
    "ml_best_ev": 0.03,
    "ml_best_quoted_at": "2026-11-18T12:00:00",
}


@pytest.fixture(autouse=True)
def _env(monkeypatch, request):
    if "sqlite_db" in request.fixturenames:  # Postgres timezone(tz, ts) on sqlite
        db = request.getfixturevalue("sqlite_db")
        db.connection().connection.create_function("timezone", 2, lambda _tz, x: x)
    monkeypatch.delenv("AUTO_PICK_PROVE_IN_KEYS", raising=False)
    monkeypatch.delenv("AUTO_PICK_REQUIRE_PROVEN_RECORD", raising=False)


def _payload(sport):
    return {g: [dict(PICKY)] for g in api._BOARD_MARKETS[sport]}


def _assert_stripped(row, reason):
    assert row["pick_withheld"] == reason
    assert row["edge"] is None and row["recommendation"] is None
    for f in api._PICK_FIELDS & row.keys():
        assert row[f] is None, f
    assert row["projected_value"] == 24.5 and row["fanduel_line"] == 22.5


def _gate_says(monkeypatch, reasons):
    """reasons: {key: reason}; every other gated key stays open."""
    monkeypatch.setattr(
        rg,
        "withheld_keys",
        lambda db, now, keys, loaders: {k: r for k, r in reasons.items() if k in keys},
    )


@pytest.mark.parametrize("sport", list(ENDPOINTS))
def test_every_sport_withholds_what_the_gate_withholds(sport, sqlite_db, monkeypatch):
    spec = api._BOARD_MARKETS[sport]
    keys = {k for entries in spec.values() for k, _ in entries if k}
    _gate_says(monkeypatch, dict.fromkeys(keys, "losing_record"))
    out = api._withhold_board_picks(_payload(sport), sqlite_db, sport, None)
    emitted = set().union(*rg.emitted_keys().values())
    for group, entries in spec.items():
        (row,) = out[group]
        if len(entries) > 1 and entries[0][1] is not api._ALL:
            # MLB game row: three markets, each owns its fields
            assert row["ml_pick_withheld"] == "losing_record"
            assert row["ml_recommendation"] is None
            assert "pick_withheld" not in row
            continue
        # a spread + moneyline row: the spread key decides the whole row
        key = entries[0][0]
        _assert_stripped(row, "losing_record" if key in emitted else "no_record_check")


def test_open_market_keeps_its_pick_and_edge(sqlite_db, monkeypatch):
    points = ("NBA", "player_prop", "points")
    _gate_says(monkeypatch, {("NBA", "player_prop", "assists"): "losing_record"})
    out = api._withhold_board_picks(_payload("nba"), sqlite_db, "nba", None)
    assert out["points"][0]["edge"] == 2.0
    assert out["points"][0]["recommendation"] == "OVER"
    assert "pick_withheld" not in out["points"][0]
    assert points in {k for e in api._BOARD_MARKETS["nba"].values() for k, _ in e}
    _assert_stripped(out["assists"][0], "losing_record")


def test_nba_points_edge_cleared_by_the_real_gate(sqlite_db, monkeypatch):
    # Prove-in on points, no record: the real gate withholds it.
    monkeypatch.setenv("AUTO_PICK_PROVE_IN_KEYS", "NBA/player_prop/points")
    monkeypatch.setenv("AUTO_PICK_REQUIRE_PROVEN_RECORD", "false")
    out = api._withhold_board_picks(_payload("nba"), sqlite_db, "nba", None)
    _assert_stripped(out["points"][0], "unproven_record")
    assert out["assists"][0]["edge"] == 2.0  # not prove-in, no data: stays open
    # Default (require-proven on): every NBA prop key, PRA included, is unproven.
    monkeypatch.delenv("AUTO_PICK_REQUIRE_PROVEN_RECORD")
    out = api._withhold_board_picks(_payload("nba"), sqlite_db, "nba", None)
    for group in ("points", "assists", "rebounds", "three_point", "steals", "pra"):
        _assert_stripped(out[group][0], "unproven_record")


def test_pra_goes_through_the_gate_like_every_nba_prop(sqlite_db, monkeypatch):
    # PRA has a gate key and loader (pra_ou), so the gate decides it, as for WNBA.
    seen = []
    monkeypatch.setattr(
        rg,
        "withheld_keys",
        lambda db, now, keys, loaders: seen.append((set(keys), loaders)) or {},
    )
    for sport in ("nba", "wnba"):
        out = api._withhold_board_picks(_payload(sport), sqlite_db, sport, None)
        assert out["pra"][0]["edge"] == 2.0
    nba_keys, nba_loaders = seen[0]
    assert "nba_props" in nba_loaders
    for stat in ("points", "assists", "rebounds", "threes", "steals", "pra"):
        assert ("NBA", "player_prop", stat) in nba_keys


def test_mlb_game_row_strips_only_the_withheld_market(sqlite_db, monkeypatch):
    row = {
        "id": 1,
        "market_total": 8.5,
        "ml_recommendation": "home",
        "edge_vs_market_ml": 0.05,
        "spread_recommendation": "home",
        "total_recommendation": "OVER",
        "edge_vs_market_total": 0.4,
        "value_rating": 3,
    }
    _gate_says(monkeypatch, {})
    out = api._withhold_board_picks({"game_projections": [row]}, sqlite_db, "mlb", None)
    (r,) = out["game_projections"]
    assert r["ml_recommendation"] == "home" and r["edge_vs_market_ml"] == 0.05
    assert r["spread_recommendation"] is None and r["total_recommendation"] is None
    assert r["edge_vs_market_total"] is None and r["value_rating"] is None
    assert r["market_total"] == 8.5
    # Per-market flags: the open moneyline is not hidden by its withheld neighbours.
    assert r["spread_pick_withheld"] == r["total_pick_withheld"] == "no_record_check"
    assert "ml_pick_withheld" not in r and "pick_withheld" not in r


def test_stake_and_book_fields_are_stripped(sqlite_db, monkeypatch):
    _gate_says(monkeypatch, {("NFL", "player_prop", "passing_yards"): "losing_record"})
    row = {**PICKY, "bet_size": 1.5, "best_over_book": "dk", "best_under_book": "fd"}
    out = api._withhold_board_picks({"qb_predictions": [row]}, sqlite_db, "nfl", None)
    (r,) = out["qb_predictions"]
    assert r["bet_size"] is None and r["best_over_book"] is None
    assert r["best_under_book"] is None


def test_gate_failure_withholds_everything(sqlite_db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(rg, "withheld_keys", boom)
    for sport in ENDPOINTS:
        out = api._withhold_board_picks(_payload(sport), sqlite_db, sport, None)
        for group, entries in api._BOARD_MARKETS[sport].items():
            (row,) = out[group]
            if len(entries) > 1:  # MLB game row: the gated moneyline fails closed
                assert row["ml_pick_withheld"] == "record_unavailable"
                continue
            assert row["pick_withheld"] in ("record_unavailable", "no_record_check")
            assert row.get("edge") is None and row["recommendation"] is None


def test_past_slates_keep_graded_calls(sqlite_db):
    past = api.eastern_today().replace(year=2020)
    payload = {
        g: [{**r, "date": past} for r in rows] for g, rows in _payload("nba").items()
    }
    out = api._withhold_board_picks(payload, sqlite_db, "nba", past)
    assert out["points"][0]["edge"] == 2.0


@pytest.mark.parametrize("sport", list(ENDPOINTS))
def test_every_board_group_has_a_market_mapping(sport, sqlite_db):
    kw = dict(
        target_date=api.eastern_today(), tz="UTC", limit=50, _user={}, db=sqlite_db
    )
    if sport in ("nba", "wnba"):
        kw["prop_limit"] = 50
    if sport == "mlb":
        kw["total_line"] = None
    out = ENDPOINTS[sport](**kw)
    lists = {k for k, v in out.items() if isinstance(v, list)}
    assert lists == set(api._BOARD_MARKETS[sport])


def test_nfl_endpoint_gates_spreads_and_always_withholds_td_and_kickers(
    sqlite_db, monkeypatch
):
    today = api.eastern_today()
    for i, p in enumerate((0.2, 0.6, 0.4)):
        sqlite_db.add(
            NFLAnytimeTDPredictions(
                player_id=f"p{i}",
                player_name=f"P{i}",
                position="WR",
                team_name="T",
                opponent_team_name="O",
                expected_tds=0.5,
                season=2026,
                week=1,
                game_date=today,
                td_probability=p,
                edge=0.9 - i * 0.3,  # SQL order would be p0, p1, p2
                recommendation="BET",
            )
        )
    sqlite_db.add(
        KickerPredictions(
            kicker_player_id="k1",
            kicker_player_name="K",
            team_id=1,
            team_name="T",
            opponent_team_name="O",
            venue_name="V",
            game_date=datetime.utcnow(),
            predicted_fg_attempts=2.0,
            predicted_fg_made=1.5,
            predicted_success_rate=0.8,
        )
    )
    sqlite_db.commit()
    _gate_says(monkeypatch, {})
    out = api.nfl_predictions(
        target_date=today, tz="UTC", limit=50, _user={}, db=sqlite_db
    )
    atd = out["anytime_td_predictions"]
    assert [r["td_probability"] for r in atd] == [0.6, 0.4, 0.2]
    for r in atd + out["kicker_predictions"]:
        assert r["pick_withheld"] == "no_record_check"
        assert r["edge"] is None and r["recommendation"] is None


def test_nhl_endpoint_runs_the_real_gate(sqlite_db):
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
            edge=1.0,
            betting_recommendation="OVER 5.5",
        )
    )
    sqlite_db.commit()
    out = api.nhl_predictions(
        target_date=today, tz="UTC", limit=50, _user={}, db=sqlite_db
    )
    (row,) = out["team_totals"]
    assert row["edge"] is None and row["betting_recommendation"] is None
    assert row["pick_withheld"] == "unproven_record"
    assert row["predicted_total_goals"] == 6.5


def test_past_date_keeps_past_games_and_withholds_unplayed_rows(sqlite_db, monkeypatch):
    # A past-date request can carry rows of games not yet played (the NFL week fallback
    # serves the whole week): those are withheld like today's; past games keep their call.
    _gate_says(monkeypatch, {("NFL", "spread", None): "unproven_record"})
    monkeypatch.setattr(api, "eastern_today", lambda: date(2026, 11, 18))
    rows = [
        {"id": 1, "game_date": "2026-11-16", "recommendation": "HOME", "edge": 3.0},
        {
            "id": 2,
            "game_date": date(2026, 11, 22),
            "recommendation": "AWAY",
            "edge": 4.0,
        },
        {"id": 3, "recommendation": "AWAY", "edge": 4.0},  # no date: withheld
    ]
    out = api._withhold_board_picks(
        {"spreads": rows}, sqlite_db, "nfl", date(2026, 11, 17)
    )
    played, unplayed, undated = out["spreads"]
    assert played["recommendation"] == "HOME" and played["edge"] == 3.0
    for r in (unplayed, undated):
        assert r["pick_withheld"] == "unproven_record"
        assert r["recommendation"] is None and r["edge"] is None


def test_best_quote_fields_are_stripped_with_the_pick(sqlite_db, monkeypatch):
    _gate_says(monkeypatch, {("NBA", "player_prop", "points"): "unproven_record"})
    row = {
        "id": 1,
        "fanduel_line": 24.5,
        "fanduel_over_under": "o",
        "fanduel_price": -110,
        "best_book": "dk",
        "best_line": 24.5,
        "best_price": 100,
        "best_fair_prob": 0.55,
        "best_ev": 0.07,
        "best_quoted_at": "2026-11-18T17:00:00",
    }
    (r,) = api._withhold_board_picks({"points": [row]}, sqlite_db, "nba", None)[
        "points"
    ]
    assert r["fanduel_line"] == 24.5  # the line stays
    for f in ("fanduel_price", "best_book", "best_line", "best_price", "best_fair_prob", "best_ev", "best_quoted_at"):  # fmt: skip
        assert r[f] is None, f


NEW_FIELDS = ("best_book", "best_line", "best_price", "best_side")
ML_FIELDS = tuple(f for f in PICKY if f.startswith("ml_best_"))


@pytest.mark.parametrize("league", ["NBA", "NFL"])
def test_best_quote_fields_follow_their_own_market(league, sqlite_db, monkeypatch):
    sport = league.lower()
    spread, ml = (league, "spread", None), (league, "moneyline", None)
    # every key unproven: the new fields are stripped on every board group
    keys = {
        k for entries in api._BOARD_MARKETS[sport].values() for k, _ in entries if k
    }
    _gate_says(monkeypatch, dict.fromkeys(keys, "unproven_record"))
    out = api._withhold_board_picks(_payload(sport), sqlite_db, sport, None)
    for group, rows in out.items():
        for f in NEW_FIELDS + ML_FIELDS:
            assert rows[0][f] is None, (group, f)
    # spread proven, moneyline not: this sparse row forms no pick candidate, so the open
    # spread shows no pick either (a passing row keeps its quote: test_board_open_game_picks)
    _gate_says(monkeypatch, {ml: "unproven_record"})
    row = api._withhold_board_picks(_payload(sport), sqlite_db, sport, None)["spreads"][
        0
    ]
    assert all(row[f] is None for f in NEW_FIELDS + ML_FIELDS)
    assert row["ml_pick_withheld"] == "unproven_record" and "pick_withheld" not in row
    # moneyline proven, spread not: conservative, the whole row goes
    _gate_says(monkeypatch, {spread: "losing_record"})
    row = api._withhold_board_picks(_payload(sport), sqlite_db, sport, None)["spreads"][
        0
    ]
    assert all(row[f] is None for f in NEW_FIELDS + ML_FIELDS)
    # both proven: open, but no candidate from a sparse row -> no pick, no withheld note
    _gate_says(monkeypatch, {})
    row = api._withhold_board_picks(_payload(sport), sqlite_db, sport, None)["spreads"][
        0
    ]
    assert all(row[f] is None for f in NEW_FIELDS + ML_FIELDS)
    assert "pick_withheld" not in row and "ml_pick_withheld" not in row
