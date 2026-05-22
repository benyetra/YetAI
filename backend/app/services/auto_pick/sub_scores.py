from app.services.auto_pick.candidate import BetCandidate, MarketType

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
