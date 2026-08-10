from pathlib import Path

from app.services.etl.nfl.scheme_loader import _PRIMARY_ABBRS, load_schemes_from_yaml


def test_load_schemes_has_thirty_two_teams(tmp_path: Path):
    schemes = load_schemes_from_yaml()
    primary_keys = {k for k in schemes if k in _PRIMARY_ABBRS}
    assert primary_keys == set(_PRIMARY_ABBRS)
    assert len(primary_keys) == 32
    sample = next(iter(schemes.values()))
    assert "cover_base" in sample
    assert "man_zone_lean" in sample
    assert "pressure_lean" in sample


def test_load_schemes_full_name_alias():
    schemes = load_schemes_from_yaml()
    assert "KC" in schemes
    assert "Kansas City Chiefs" in schemes
    assert schemes["KC"] == schemes["Kansas City Chiefs"]
