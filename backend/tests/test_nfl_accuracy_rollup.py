"""H-3/H-4/H-5/H-6 service-level checks: tiles, overview and per-row results agree."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

from app.services import nfl_accuracy_service as svc

D = date(2026, 9, 13)


def _mock_db(rows_by_model):
    db = MagicMock()

    def side_effect(model):
        result = MagicMock()
        result.filter.return_value.all.return_value = rows_by_model.get(
            model.__name__, []
        )
        return result

    db.query.side_effect = side_effect
    return db


def _game(i, **kw):
    return NS(game_date=D, home_team_name=f"H{i}", away_team_name=f"A{i}", id=i, **kw)


def _fixture():
    # totals (probe-nfl-rollup): 1 real OVER hit + 3 NO_PLAY rows, game played
    totals_p = [
        _game(1, projected_total=48, market_total=45, recommendation="OVER"),
        _game(2, projected_total=45, market_total=44, recommendation="NO_PLAY"),
        _game(3, projected_total=44, market_total=45, recommendation="NO_PLAY"),
        _game(4, projected_total=46, market_total=47, recommendation="NO_PLAY"),
    ]
    totals_a = [
        _game(i, actual_total=50, home_actual_score=30, away_actual_score=20)
        for i in (1, 2, 3, 4)
    ]
    # spreads: HOME hit, AWAY miss, HOME push
    spread_p = [
        _game(1, projected_margin=5, market_spread_home=-3.0, recommendation="HOME"),
        _game(2, projected_margin=-5, market_spread_home=-3.0, recommendation="AWAY"),
        _game(3, projected_margin=5, market_spread_home=-3.0, recommendation="HOME"),
    ]
    spread_a = [
        _game(1, actual_margin=7, home_score=27, away_score=20, home_won=True),
        _game(2, actual_margin=7, home_score=27, away_score=20, home_won=True),
        _game(3, actual_margin=3, home_score=23, away_score=20, home_won=True),
    ]
    # QB: OVER hit, PASS (not a call), OVER with no actual (voided)
    qb_p = [
        NS(
            id=1,
            qb_player_id="a",
            game_date=D,
            predicted_passing_yards=280,
            ou_line=250,
            betting_recommendation="OVER",
        ),
        NS(
            id=2,
            qb_player_id="b",
            game_date=D,
            predicted_passing_yards=255,
            ou_line=250,
            betting_recommendation="PASS",
        ),
        NS(
            id=3,
            qb_player_id="c",
            game_date=D,
            predicted_passing_yards=270,
            ou_line=250,
            betting_recommendation="OVER",
        ),
    ]
    qb_a = [
        NS(qb_player_id="a", game_date=D, actual_passing_yards=300),
        NS(qb_player_id="b", game_date=D, actual_passing_yards=300),
    ]
    # receiving: UNDER hit, OVER miss, OVER with no actual (DNP)
    rv_p = [
        NS(
            id=1,
            player_id="r1",
            game_date=D,
            predicted_receiving_yards=50,
            ou_line=60,
            betting_recommendation="UNDER",
        ),
        NS(
            id=2,
            player_id="r2",
            game_date=D,
            predicted_receiving_yards=70,
            ou_line=60,
            betting_recommendation="OVER",
        ),
        NS(
            id=3,
            player_id="r3",
            game_date=D,
            predicted_receiving_yards=70,
            ou_line=60,
            betting_recommendation="OVER",
        ),
    ]
    rv_a = [
        NS(player_id="r1", game_date=D, actual_receiving_yards=40),
        NS(player_id="r2", game_date=D, actual_receiving_yards=30),
    ]
    return _mock_db(
        {
            "NFLTotalsProjections": totals_p,
            "NFLTotalsActuals": totals_a,
            "NFLSpreadProjections": spread_p,
            "NFLSpreadActuals": spread_a,
            "QBPredictions": qb_p,
            "QBActuals": qb_a,
            "RecvYdsPredictions": rv_p,
            "RecvYdsActuals": rv_a,
        }
    )


def _tiles(db):
    return {b["key"]: b for b in svc.daily_accuracy(db, target_date=D)["buckets"]}


def test_totals_and_qb_tiles_do_not_count_no_play_or_pass_as_losses():
    """H-3: tile now equals the overview's graded counts on the probe cases."""
    db = _fixture()
    tiles = _tiles(db)
    assert tiles["totals_ou"]["primary"] == "1/1 · 100%"
    assert tiles["qb_passing_ou"]["primary"] == "1/1 · 100%"
    markets = {
        m["market"]: (m["correct"], m["graded"])
        for m in svc.season_overview(db, start=D, end=D)["markets"]
    }
    assert markets["Game Totals O/U"] == (1, 1)
    assert markets["QB Pass Yds O/U"] == (1, 1)


def test_qb_tile_shows_voided_count():
    """NFL-7: a lined QB with no actual shows as a no-actual count."""
    assert "1 no actual" in _tiles(_fixture())["qb_passing_ou"]["secondary"]


def test_receiving_yards_tile_and_overview():
    """H-5/NFL-5: receiving yards O/U exists as a tile (with MAE) and in the overview."""
    db = _fixture()
    recv = _tiles(db)["recv_yds_ou"]
    assert recv["primary"] == "1/2 · 50%"
    assert "MAE" in recv["secondary"]
    markets = {m["market"] for m in svc.season_overview(db, start=D, end=D)["markets"]}
    assert {"Receiving Yds O/U", "Game Totals O/U", "Spread ATS"} <= markets


def test_overview_has_spreads_ats_and_totals():
    """H-5/NFL-4: spreads ATS (push excluded) and totals are in the NFL number."""
    item = svc.season_overview(_fixture(), start=D, end=D)
    by_market = {m["market"]: (m["correct"], m["graded"]) for m in item["markets"]}
    assert by_market["Spread ATS"] == (1, 2)
    assert item["graded_count"] == 1 + 1 + 2 + 2  # qb + totals + recv + spreads
    diag = svc.season_overview_diagnostics(_fixture(), start=D, end=D)
    assert {p["key"] for p in diag["parts"]} == {
        "qb_passing_ou",
        "recv_yds_ou",
        "totals_ou",
        "spread_ats",
    }


def test_past_row_results_agree_with_tiles():
    """H-4: per-row results, tiles and overview count the same hits/misses."""
    db = _fixture()
    rows = svc.past_row_results(db, target_date=D)
    res = lambda k: {i: r["result"] for i, r in rows[k].items()}  # noqa: E731

    assert res("totals") == {1: "hit", 2: "no_play", 3: "no_play", 4: "no_play"}
    assert res("spreads") == {1: "hit", 2: "miss", 3: "push"}
    assert res("qb_predictions") == {1: "hit", 2: "no_play", 3: "dnp"}
    assert res("receiving_yards_predictions") == {1: "hit", 2: "miss", 3: "dnp"}
    assert rows["totals"][1]["actual_home_score"] == 30
    assert rows["totals"][1]["actual_total"] == 50
    assert rows["spreads"][1]["actual_winner"] == "home"

    tiles = _tiles(db)
    for tile, key in (
        ("totals_ou", "totals"),
        ("spread_ats", "spreads"),
        ("qb_passing_ou", "qb_predictions"),
        ("recv_yds_ou", "receiving_yards_predictions"),
    ):
        r = list(res(key).values())
        hits, misses = r.count("hit"), r.count("miss")
        assert tiles[tile]["primary"].startswith(f"{hits}/{hits + misses} ")
