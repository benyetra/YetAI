from pathlib import Path

from app.services.etl.nfl.scheme_loader import (
    SEASON_LEVEL_WEEK,
    _PRIMARY_ABBRS,
    db_row_to_scheme_tags,
    decode_cover_base,
    decode_man_zone_lean,
    decode_pressure_lean,
    load_schemes_from_yaml,
    yaml_entry_to_db_row,
)


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


def test_season_level_week_sentinel():
    assert SEASON_LEVEL_WEEK == 0


def test_yaml_entry_to_db_row_defaults_to_season_week():
    row = yaml_entry_to_db_row("KC", {"cover_base": "cover_3"}, season=2026)
    assert row["week"] == SEASON_LEVEL_WEEK


def test_decode_scheme_tags_round_trip():
    assert decode_cover_base(3) == "cover_3"
    assert decode_man_zone_lean(0.0) == "zone"
    assert decode_pressure_lean(0.75) == "high"
    tags = db_row_to_scheme_tags(
        {"cover_base": 3, "man_zone_lean": 0.0, "pressure_lean": 0.75}
    )
    assert tags == {
        "cover_base": "cover_3",
        "man_zone_lean": "zone",
        "pressure_lean": "high",
    }
