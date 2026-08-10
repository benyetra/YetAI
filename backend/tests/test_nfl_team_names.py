from app.services.etl.nfl.team_names import normalize_team_name


def test_normalize_common_aliases():
    assert normalize_team_name("LA Rams") == "Los Angeles Rams"
    assert normalize_team_name("Washington Football Team") == "Washington Commanders"
    assert normalize_team_name("Washington Commanders") == "Washington Commanders"
