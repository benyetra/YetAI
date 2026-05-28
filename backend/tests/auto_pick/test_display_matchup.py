from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.orchestrator import display_matchup_title


def _cand(**kwargs) -> BetCandidate:
    defaults = dict(
        market_type=MarketType.PLAYER_PROP,
        league="MLB",
        event_id="e1",
        selection="Christian Scott UNDER 4.5 strikeouts",
        market_line=4.5,
        market_odds=-110,
        our_projection=3.2,
    )
    defaults.update(kwargs)
    return BetCandidate(**defaults)


def test_display_matchup_uses_away_at_home():
    c = _cand(away_team="Mets", home_team="Phillies")
    assert display_matchup_title(c) == "Mets @ Phillies"


def test_display_matchup_uses_team_vs_opponent_from_metadata():
    c = _cand(
        projection_metadata={"team": "Mets", "opponent": "Phillies"},
    )
    assert display_matchup_title(c) == "Mets @ Phillies"


def test_display_matchup_opponent_only():
    c = _cand(projection_metadata={"opponent": "Oklahoma City Thunder"})
    assert display_matchup_title(c) == "vs Oklahoma City Thunder"


def test_display_matchup_falls_back_to_player_prop_label():
    c = _cand()
    assert display_matchup_title(c) == "MLB player prop"
