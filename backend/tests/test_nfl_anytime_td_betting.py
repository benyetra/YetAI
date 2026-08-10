"""Tests for NFL anytime-TD Odds attach (pure odds math + parse, no live API)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.etl.nfl.anytime_td_betting import (
    ANYTIME_TD_EDGE_THRESHOLD,
    american_to_implied_prob,
    attach_betting_fields,
    compute_edge,
    match_player_odds,
    normalize_player_name,
    parse_player_anytime_td_outcomes,
    recommendation_for_edge,
    run,
)


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


def test_attach_betting_fields():
    fields = attach_betting_fields(td_probability=0.55, market_odds=-110)
    assert fields["market_odds"] == -110
    assert 0 < fields["market_implied_prob"] < 1
    assert fields["edge"] == pytest.approx(
        0.55 - fields["market_implied_prob"], abs=1e-9
    )
    assert fields["recommendation"] in ("OVER", "NO_PLAY")


def test_parse_player_anytime_td_outcomes_keeps_best_yes_odds():
    payload = {
        "bookmakers": [
            {
                "key": "fanduel",
                "title": "FanDuel",
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
                "title": "DraftKings",
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
        ]
    }
    odds = parse_player_anytime_td_outcomes(payload)
    assert odds["Patrick Mahomes"] == -105


def test_normalize_and_match_player_name():
    assert normalize_player_name("CJ Stroud") == "C.J. Stroud"
    odds = {"C.J. Stroud": -150, "Travis Kelce": -110}
    assert match_player_odds("CJ Stroud", odds) == -150
    assert match_player_odds("Kelce", odds) == -110
    assert match_player_odds("Unknown Player", odds) is None


def test_run_attaches_odds_to_predictions():
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
    pred.features = {}
    pred.model_version = "hierarchical_v1"
    pred.prediction_date = __import__("datetime").datetime.utcnow()
    pred.created_at = pred.prediction_date

    mock_db = MagicMock()
    mock_db.query.return_value.filter_by.return_value.all.return_value = [pred]

    with (
        patch(
            "app.services.etl.nfl.anytime_td_betting.SessionLocal", return_value=mock_db
        ),
        patch(
            "app.services.etl.nfl.anytime_td_betting.fetch_anytime_td_odds",
            return_value={"Travis Kelce": -110},
        ),
        patch("app.services.etl.nfl.anytime_td_betting.upsert_many") as um,
    ):
        um.return_value = 1
        result = run(season=2025, week=5)

    assert result["status"] == "ok"
    assert result["matched"] == 1
    um.assert_called_once()
    row = um.call_args[0][2][0]
    assert row["market_odds"] == -110
    assert row["recommendation"] in ("OVER", "NO_PLAY")
