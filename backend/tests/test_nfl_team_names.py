from app.services.etl.nfl.team_names import (
    normalize_team_name,
    team_identity_tokens,
    team_name_to_abbr,
)


def test_normalize_common_aliases():
    assert normalize_team_name("LA Rams") == "Los Angeles Rams"
    assert normalize_team_name("Washington Football Team") == "Washington Commanders"
    assert normalize_team_name("Washington Commanders") == "Washington Commanders"


def test_team_name_to_abbr():
    assert team_name_to_abbr("Buffalo Bills") == "BUF"
    assert team_name_to_abbr("BUF") == "BUF"
    assert team_name_to_abbr("LA Rams") == "LAR"
    assert "BUF" in team_identity_tokens("Buffalo Bills")
    assert "Buffalo Bills" in team_identity_tokens("BUF")
