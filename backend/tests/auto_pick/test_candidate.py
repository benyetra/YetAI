from datetime import datetime
from app.services.auto_pick.candidate import (
    BetCandidate, MarketType, CandidateProvider,
)

def test_bet_candidate_required_fields():
    c = BetCandidate(
        market_type=MarketType.PLAYER_PROP,
        league="MLB",
        event_id="mlb-2026-05-22-bos-nyy",
        selection="Spencer Strider OVER 5.5 Ks",
        market_line=5.5,
        market_odds=-115,
        our_projection=9.0,
        projection_metadata={"sample_size": 7, "model_id": "mlb_k_v2", "generated_at": datetime.utcnow().isoformat()},
    )
    assert c.market_type == MarketType.PLAYER_PROP
    assert c.our_projection == 9.0

def test_candidate_provider_is_protocol():
    class FakeProvider:
        async def get_candidates(self, date_range):
            return []
    assert isinstance(FakeProvider(), CandidateProvider)
