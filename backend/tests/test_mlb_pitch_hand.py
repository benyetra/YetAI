"""Pitch-hand normalization for MLB statsapi strings."""

from app.services.etl.mlb._mlb_utils import normalize_pitch_hand


def test_normalize_pitch_hand_statsapi_labels():
    assert normalize_pitch_hand("Right") == "R"
    assert normalize_pitch_hand("Left") == "L"


def test_normalize_pitch_hand_codes():
    assert normalize_pitch_hand("R") == "R"
    assert normalize_pitch_hand("l") == "L"


def test_normalize_pitch_hand_default_right():
    assert normalize_pitch_hand(None) == "R"
    assert normalize_pitch_hand("") == "R"
