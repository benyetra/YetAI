"""Unit tests for ATD market-anchor vig-free fair P, shrink, and edge gates."""

from __future__ import annotations

import pytest

from app.services.etl.nfl.anytime_td_market_anchor import (
    YES_ONLY_OVERROUND,
    american_ev,
    american_to_implied_prob,
    blend_publish_prob,
    market_anchor_signal_score,
    recommendation_for_market_edge,
    shrink_weight,
    stamp_market_model_version,
    vig_free_fair_prob,
)


def test_vig_free_yes_no_removes_overround():
    fair, src = vig_free_fair_prob(-110, -110)
    assert src == "yes_no_vigfree"
    assert fair == pytest.approx(0.5, abs=1e-6)


def test_yes_only_haircut_documented():
    implied = american_to_implied_prob(-290)
    fair, src = vig_free_fair_prob(-290, None)
    assert src == "yes_only_haircut"
    assert fair == pytest.approx(implied / (1.0 + YES_ONLY_OVERROUND), abs=1e-9)


def test_gibbs_class_weak_signal_edge_not_catastrophic():
    """Screenshot class: model ~34% vs −290 must not show ~−44% edge after anchor."""
    p_model = 0.34
    p_fair, _ = vig_free_fair_prob(-290, None)
    features = {
        "week": 1,
        "gl_carries": None,
        "rz_targets": None,
        "td_l3": None,
        "availability_mult": 1.0,
        "injury_status": None,
        "script_mult": 1.0,
        "depth_team": 1,
    }
    w = shrink_weight(market_anchor_signal_score(features))
    assert w <= 0.15
    p_pub = blend_publish_prob(p_fair, p_model, w)
    edge = p_pub - p_fair
    assert abs(edge) < 0.08
    assert (
        recommendation_for_market_edge(edge, ev=american_ev(p_pub, -290)) == "NO_PLAY"
    )


def test_strong_injury_signal_allows_deviation():
    features = {
        "week": 8,
        "gl_carries": 6,
        "rz_targets": 8,
        "td_l3": 2,
        "availability_mult": 0.75,
        "injury_status": "Questionable",
        "script_mult": 1.12,
        "depth_team": 2,
    }
    signal = market_anchor_signal_score(features)
    assert signal >= 0.5
    assert shrink_weight(signal) >= 0.5


def test_week1_thin_form_near_full_anchor():
    features = {
        "week": 1,
        "gl_carries": None,
        "rz_targets": None,
        "td_l3": None,
        "availability_mult": 1.0,
        "script_mult": 1.0,
        "depth_team": 1,
    }
    assert market_anchor_signal_score(features) == pytest.approx(0.0)
    assert shrink_weight(0.0) == pytest.approx(0.05)


def test_recommendation_over_requires_edge_and_positive_ev():
    assert recommendation_for_market_edge(0.06, ev=0.02) == "OVER"
    assert recommendation_for_market_edge(0.06, ev=-0.01) == "NO_PLAY"
    assert recommendation_for_market_edge(-0.06, ev=-0.05) == "UNDER"
    assert recommendation_for_market_edge(0.01, ev=0.05) == "NO_PLAY"


def test_stamp_market_model_version_once():
    assert stamp_market_model_version("hierarchical_v1") == "hierarchical_v1_mkt"
    assert stamp_market_model_version("hierarchical_v1_mkt") == "hierarchical_v1_mkt"
    assert (
        stamp_market_model_version("hierarchical_v1_gbm_pos")
        == "hierarchical_v1_gbm_pos_mkt"
    )
