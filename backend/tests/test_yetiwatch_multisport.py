"""Tests for multi-sport YetiWatch registry."""

import pytest

from app.services.etl.yetiwatch.sports.registry import SUPPORTED_SPORTS, get_adapter


@pytest.mark.parametrize("sport", ["nba", "wnba", "mlb", "nfl", "nhl"])
def test_get_adapter_supported_sports(sport):
    adapter = get_adapter(sport)
    assert adapter.sport == sport


def test_supported_sports_list():
    assert set(SUPPORTED_SPORTS) == {"nba", "wnba", "mlb", "nfl", "nhl"}


def test_get_adapter_unknown_sport():
    with pytest.raises(ValueError, match="Unsupported"):
        get_adapter("soccer")
