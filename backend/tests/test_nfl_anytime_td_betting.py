"""Tests for NFL anytime-TD Odds attach (pure odds math + parse, no live API)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.etl.nfl.anytime_td_betting import (
    ANYTIME_TD_EDGE_THRESHOLD,
    american_to_implied_prob,
    attach_betting_fields,
    clear_betting_fields,
    compute_edge,
    consensus_anytime_td_quote,
    match_player_odds,
    normalize_player_name,
    parse_player_anytime_td_book_quotes,
    parse_player_anytime_td_outcomes,
    recommendation_for_edge,
    run,
)
from app.services.etl.nfl.anytime_td_market_anchor import vig_free_fair_prob


def test_american_to_implied_prob_negative():
    assert abs(american_to_implied_prob(-150) - 0.6) < 1e-9


def test_american_to_implied_prob_positive():
    assert abs(american_to_implied_prob(200) - (100 / 300)) < 1e-9


def test_compute_edge_and_recommendation():
    implied = american_to_implied_prob(-110)
    edge = compute_edge(0.60, implied)
    assert edge > 0
    assert recommendation_for_edge(edge) == "OVER"
    assert recommendation_for_edge(0.01) == "NO_PLAY"
    assert recommendation_for_edge(ANYTIME_TD_EDGE_THRESHOLD) == "OVER"


def test_attach_betting_fields_market_anchor():
    fields = attach_betting_fields(
        td_probability=0.55,
        market_odds=-110,
        market_odds_no=-110,
        features={"week": 8, "gl_carries": 4, "rz_targets": 6, "p_model": 0.55},
        model_version="hierarchical_v1",
    )
    assert fields["market_odds"] == -110
    assert fields["market_implied_prob"] == pytest.approx(0.5, abs=1e-6)
    assert fields["edge"] == pytest.approx(
        fields["td_probability"] - fields["market_implied_prob"], abs=1e-9
    )
    assert fields["recommendation"] in ("OVER", "UNDER", "NO_PLAY")
    assert fields["model_version"] == "hierarchical_v1_mkt"
    assert fields["features"]["p_model"] == 0.55


def test_attach_gibbs_class_not_negative_forty_edge():
    """Screenshot class: hierarchical ~34% @ −290 must not show ~−44% edge."""
    fields = attach_betting_fields(
        td_probability=0.34,
        market_odds=-290,
        features={
            "week": 1,
            "gl_carries": None,
            "rz_targets": None,
            "td_l3": None,
            "availability_mult": 1.0,
            "script_mult": 1.0,
            "p_model": 0.34,
        },
        model_version="hierarchical_v1",
    )
    assert abs(fields["edge"]) < 0.08
    assert fields["recommendation"] == "NO_PLAY"
    assert fields["td_probability"] == pytest.approx(
        fields["market_implied_prob"] + fields["edge"], abs=1e-9
    )
    # Old definition would be ~-0.40 vs juiced implied.
    juiced = american_to_implied_prob(-290)
    assert (0.34 - juiced) < -0.35


def test_parse_prefers_pinnacle_consensus():
    payload = {
        "bookmakers": [
            {
                "key": "fanduel",
                "title": "FanDuel",
                "last_update": "2026-09-10T12:00:00Z",
                "markets": [
                    {
                        "key": "player_anytime_td",
                        "outcomes": [
                            {
                                "name": "Yes",
                                "description": "Jahmyr Gibbs",
                                "price": -250,
                            },
                            {
                                "name": "No",
                                "description": "Jahmyr Gibbs",
                                "price": +180,
                            },
                        ],
                    }
                ],
            },
            {
                "key": "pinnacle",
                "title": "Pinnacle",
                "last_update": "2026-09-10T12:05:00Z",
                "markets": [
                    {
                        "key": "player_anytime_td",
                        "outcomes": [
                            {
                                "name": "Yes",
                                "description": "Jahmyr Gibbs",
                                "price": -290,
                            },
                            {
                                "name": "No",
                                "description": "Jahmyr Gibbs",
                                "price": +210,
                            },
                        ],
                    }
                ],
            },
        ]
    }
    quotes = parse_player_anytime_td_book_quotes(payload)
    cons = consensus_anytime_td_quote(quotes["Jahmyr Gibbs"])
    assert cons is not None
    assert cons["book"] == "pinnacle"
    assert cons["yes"] == -290
    assert cons["no"] == 210
    odds = parse_player_anytime_td_outcomes(payload)
    assert odds["Jahmyr Gibbs"] == -290


def test_parse_median_soft_books_without_pinnacle():
    payload = {
        "bookmakers": [
            {
                "key": "fanduel",
                "markets": [
                    {
                        "key": "player_anytime_td",
                        "outcomes": [
                            {
                                "name": "Yes",
                                "description": "Patrick Mahomes",
                                "price": -120,
                            },
                            {
                                "name": "No",
                                "description": "Patrick Mahomes",
                                "price": -110,
                            },
                        ],
                    }
                ],
            },
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "player_anytime_td",
                        "outcomes": [
                            {
                                "name": "Yes",
                                "description": "Patrick Mahomes",
                                "price": -105,
                            }
                        ],
                    }
                ],
            },
            {
                "key": "betmgm",
                "markets": [
                    {
                        "key": "player_anytime_td",
                        "outcomes": [
                            {
                                "name": "Yes",
                                "description": "Patrick Mahomes",
                                "price": -115,
                            }
                        ],
                    }
                ],
            },
        ]
    }
    # Median of -120, -105, -115 = -115
    assert parse_player_anytime_td_outcomes(payload)["Patrick Mahomes"] == -115


def test_normalize_and_match_player_name():
    assert normalize_player_name("CJ Stroud") == "C.J. Stroud"
    odds = {"C.J. Stroud": -150, "Travis Kelce": -110}
    assert match_player_odds("CJ Stroud", odds) == -150
    assert match_player_odds("Kelce", odds) == -110
    assert match_player_odds("Unknown Player", odds) is None


def test_match_player_odds_last_name_only_odds_key():
    odds = {"Kelce": -110}
    assert match_player_odds("Travis Kelce", odds) == -110


def test_match_player_odds_rejects_ambiguous_last_name():
    odds = {"A.J. Brown": -120, "Antonio Brown": -130}
    assert match_player_odds("Brown", odds) is None


def test_match_player_odds_no_substring_false_positive():
    odds = {"Johnson": -110, "Peterson": -120}
    assert match_player_odds("son", odds) is None


def test_match_player_odds_quote_dict():
    odds = {
        "Travis Kelce": {
            "yes": -110,
            "no": -120,
            "book": "pinnacle",
            "last_update": None,
        }
    }
    assert match_player_odds("Travis Kelce", odds)["yes"] == -110


def test_clear_betting_fields():
    cleared = clear_betting_fields()
    assert cleared == {
        "market_odds": None,
        "market_implied_prob": None,
        "edge": None,
        "recommendation": None,
    }


def _mock_pred(**overrides):
    pred = MagicMock()
    pred.season = 2025
    pred.week = 5
    pred.player_id = "p1"
    pred.player_name = "Travis Kelce"
    pred.game_date = __import__("datetime").date(2025, 10, 5)
    pred.position = "TE"
    pred.team_name = "Kansas City Chiefs"
    pred.opponent_team_name = "Buffalo Bills"
    pred.expected_tds = 0.4
    pred.td_probability = 0.35
    pred.confidence_score = 0.35
    pred.features = {"week": 5, "p_model": 0.35, "p_hier": 0.35}
    pred.model_version = "hierarchical_v1"
    pred.prediction_date = __import__("datetime").datetime.utcnow()
    pred.created_at = pred.prediction_date
    pred.market_odds = None
    pred.market_implied_prob = None
    pred.edge = None
    pred.recommendation = None
    for k, v in overrides.items():
        setattr(pred, k, v)
    return pred


def test_run_attaches_odds_to_predictions():
    pred = _mock_pred()
    mock_db = MagicMock()
    mock_db.query.return_value.filter_by.return_value.all.return_value = [pred]

    with (
        patch(
            "app.services.etl.nfl.anytime_td_betting.SessionLocal", return_value=mock_db
        ),
        patch(
            "app.services.etl.nfl.anytime_td_betting.fetch_anytime_td_odds",
            return_value={
                "Travis Kelce": {
                    "yes": -110,
                    "no": -110,
                    "book": "pinnacle",
                    "last_update": "2026-09-10T12:00:00Z",
                }
            },
        ),
        patch("app.services.etl.nfl.anytime_td_betting.upsert_many") as um,
    ):
        um.return_value = 1
        result = run(season=2025, week=5)

    assert result["status"] == "ok"
    assert result["matched"] == 1
    assert result["blocked"] == 0
    um.assert_called_once()
    row = um.call_args[0][2][0]
    assert row["market_odds"] == -110
    assert row["recommendation"] in ("OVER", "UNDER", "NO_PLAY")
    assert "td_probability" in um.call_args[1]["update_keys"]
    fair, _ = vig_free_fair_prob(-110, -110)
    assert row["market_implied_prob"] == pytest.approx(fair, abs=1e-9)


def test_run_clears_stale_when_fetch_empty():
    pred = _mock_pred(
        market_odds=-290,
        market_implied_prob=0.74,
        edge=-0.40,
        recommendation="NO_PLAY",
        td_probability=0.70,
        features={"week": 1, "p_model": 0.34, "p_hier": 0.34},
    )
    mock_db = MagicMock()
    mock_db.query.return_value.filter_by.return_value.all.return_value = [pred]

    with (
        patch(
            "app.services.etl.nfl.anytime_td_betting.SessionLocal", return_value=mock_db
        ),
        patch(
            "app.services.etl.nfl.anytime_td_betting.fetch_anytime_td_odds",
            return_value={},
        ),
        patch("app.services.etl.nfl.anytime_td_betting.upsert_many") as um,
    ):
        um.return_value = 1
        result = run(season=2025, week=5)

    assert result["matched"] == 0
    assert result["blocked"] == 1
    assert result["stale_cleared"] == 1
    row = um.call_args[0][2][0]
    assert row["market_odds"] is None
    assert row["edge"] is None
    assert row["recommendation"] is None
    assert row["td_probability"] == pytest.approx(0.34)


def test_run_clears_unmatched_player():
    pred = _mock_pred(
        market_odds=-150,
        market_implied_prob=0.60,
        edge=-0.25,
        recommendation="NO_PLAY",
        features={"week": 5, "p_model": 0.35},
    )
    mock_db = MagicMock()
    mock_db.query.return_value.filter_by.return_value.all.return_value = [pred]

    with (
        patch(
            "app.services.etl.nfl.anytime_td_betting.SessionLocal", return_value=mock_db
        ),
        patch(
            "app.services.etl.nfl.anytime_td_betting.fetch_anytime_td_odds",
            return_value={
                "Other Player": {
                    "yes": -110,
                    "no": None,
                    "book": "fanduel",
                    "last_update": None,
                }
            },
        ),
        patch("app.services.etl.nfl.anytime_td_betting.upsert_many") as um,
    ):
        um.return_value = 1
        result = run(season=2025, week=5)

    assert result["matched"] == 0
    assert result["stale_cleared"] == 1
    row = um.call_args[0][2][0]
    assert row["market_odds"] is None
    assert row["edge"] is None
