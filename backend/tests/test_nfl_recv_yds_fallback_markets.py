from app.services.player_props_service import FALLBACK_PLAYER_PROP_MARKETS


def test_nfl_fallback_includes_reception_yds():
    assert (
        "player_reception_yds" in FALLBACK_PLAYER_PROP_MARKETS["americanfootball_nfl"]
    )
