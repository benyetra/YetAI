from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.scoring_context import ScoringContext

EDGE_NORMALIZERS = {
    MarketType.MONEYLINE: 0.20,
    MarketType.SPREAD: 7.0,
    MarketType.TOTAL: 7.0,
    MarketType.PLAYER_PROP: 4.0,
}


def edge_sub_score(candidate: BetCandidate) -> float:
    delta = candidate.our_projection - candidate.market_line
    norm = EDGE_NORMALIZERS[candidate.market_type]
    raw = (delta / norm) * 100.0
    if raw > 100.0:
        return 100.0
    if raw < -100.0:
        return -100.0
    return raw


def historical_sub_score(candidate: BetCandidate, context: ScoringContext) -> float:
    rate = context.historical_hit_rates.get((candidate.market_type.value, candidate.league))
    if rate is None:
        return 50.0
    if rate <= 0.40:
        return 0.0
    if rate >= 0.65:
        return 100.0
    if rate < 0.524:
        return (rate - 0.40) / (0.524 - 0.40) * 50.0
    return 50.0 + (rate - 0.524) / (0.65 - 0.524) * 50.0
