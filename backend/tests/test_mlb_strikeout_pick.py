"""Unit tests for MLB strikeout pick helpers."""

from app.services.mlb_strikeout_pick import (
    MIN_K_EDGE_FOR_AUTO_PICK,
    ev_pick_from_flag,
    k_edge,
    pick_confidence_pct,
    projection_pick_side,
    qualifies_for_auto_pick,
    signed_edge_for_side,
)


def test_projection_pick_side_over():
    assert projection_pick_side(8.2, 5.5) == "over"


def test_projection_pick_side_under():
    assert projection_pick_side(4.0, 5.5) == "under"


def test_projection_pick_side_no_line():
    assert projection_pick_side(8.0, 0) is None


def test_ev_pick_from_flag():
    assert ev_pick_from_flag("o") == "over"
    assert ev_pick_from_flag("u") == "under"
    assert ev_pick_from_flag("n") is None


def test_signed_edge_for_side_under():
    assert signed_edge_for_side(8.2, 5.5, "under") < 0
    assert signed_edge_for_side(4.0, 5.5, "under") > 0


def test_pick_confidence_high_when_large_edge():
    conf = pick_confidence_pct(8.2, 5.5, prob_over=0.85)
    assert conf >= 70.0


def test_qualifies_for_auto_pick_requires_edge():
    assert qualifies_for_auto_pick(8.2, 5.5, "over") is True
    assert qualifies_for_auto_pick(5.6, 5.5, "over") is False
    assert MIN_K_EDGE_FOR_AUTO_PICK == 0.75


def test_k_edge_sign():
    assert k_edge(8.2, 5.5) == 8.2 - 5.5
