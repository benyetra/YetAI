"""Cross-source team ID mappings for WNBA."""
from app.services.etl.wnba import _team_id_map as m


def test_all_active_teams_have_three_way_mapping():
    for wnba_id, name in m.WNBA_ID_TO_NAME.items():
        assert m.NAME_TO_WNBA_ID[name.lower()] == wnba_id


def test_odds_api_name_alias_resolves():
    assert m.normalize_team_name("LA Sparks") == "Los Angeles Sparks"
    assert m.normalize_team_name("Los Angeles Sparks") == "Los Angeles Sparks"


def test_expansion_teams_present():
    assert "Toronto Tempo" in m.WNBA_ID_TO_NAME.values()
    assert "Golden State Valkyries" in m.WNBA_ID_TO_NAME.values()


def test_espn_ids_all_resolve_to_known_wnba_ids():
    known = set(m.WNBA_ID_TO_NAME.keys())
    for espn_id, wnba_id in m.ESPN_TO_WNBA_TEAM_ID.items():
        assert wnba_id in known, f"ESPN id {espn_id} points at unknown WNBA id {wnba_id}"
