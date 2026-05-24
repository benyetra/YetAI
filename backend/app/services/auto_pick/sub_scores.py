from datetime import datetime

from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.scoring_context import ScoringContext
from app.services.mlb_strikeout_pick import signed_edge_for_side

EDGE_NORMALIZERS = {
    MarketType.MONEYLINE: 0.20,
    MarketType.SPREAD: 7.0,
    MarketType.TOTAL: 7.0,
    MarketType.PLAYER_PROP: 4.0,
}


def edge_sub_score(candidate: BetCandidate) -> float:
    side = (candidate.projection_metadata.get("side") or "").lower()
    if candidate.market_type == MarketType.PLAYER_PROP and side in ("over", "under"):
        delta = signed_edge_for_side(
            candidate.our_projection, candidate.market_line, side
        )
    else:
        delta = candidate.our_projection - candidate.market_line
    norm = EDGE_NORMALIZERS[candidate.market_type]
    raw = (delta / norm) * 100.0
    if raw > 100.0:
        return 100.0
    if raw < -100.0:
        return -100.0
    return raw


def historical_sub_score(candidate: BetCandidate, context: ScoringContext) -> float:
    rate = context.historical_hit_rates.get(
        (candidate.market_type.value, candidate.league)
    )
    if rate is None:
        return 50.0
    if rate <= 0.40:
        return 0.0
    if rate >= 0.65:
        return 100.0
    if rate < 0.524:
        return (rate - 0.40) / (0.524 - 0.40) * 50.0
    return 50.0 + (rate - 0.524) / (0.65 - 0.524) * 50.0


def freshness_sub_score(candidate: BetCandidate, context: ScoringContext) -> float:
    score = 100.0
    md = candidate.projection_metadata
    sample = md.get("sample_size", 10)
    if sample < 5:
        score -= 45
    elif sample < 10:
        score -= 20

    gen_at = md.get("generated_at")
    if gen_at and context.now:
        try:
            gen_dt = datetime.fromisoformat(gen_at)
            age_h = (context.now - gen_dt).total_seconds() / 3600.0
            if age_h > 24:
                score -= 55
            elif age_h > 12:
                score -= 15
        except ValueError:
            pass

    if md.get("injury_flag"):
        score -= 75

    return max(0.0, min(100.0, score))


def line_movement_sub_score(candidate: BetCandidate, context: ScoringContext) -> float:
    mv = context.line_movement.get(candidate.event_id)
    if not mv:
        return 50.0
    opened = mv.get("opened_line")
    current = mv.get("current_line")
    side = mv.get("side", "").lower()
    if opened is None or current is None:
        return 50.0
    delta = current - opened
    if side in ("over", "home", "favorite"):
        signed = delta
    else:
        signed = -delta
    bonus = max(-30.0, min(30.0, signed * 30.0))
    return 50.0 + bonus


def odds_sanity_sub_score(candidate: BetCandidate, context: ScoringContext) -> float:
    o = candidate.market_odds
    if -150 <= o <= 150:
        return 100.0
    if o < -150:
        return max(0.0, 100.0 - (abs(o) - 150) * (100.0 / 150.0))
    return max(0.0, 100.0 - (o - 150) * (100.0 / 250.0))


def model_confidence_sub_score(candidate: BetCandidate) -> float:
    mc = candidate.projection_metadata.get("model_confidence")
    if mc is None:
        return 50.0
    return max(0.0, min(100.0, float(mc) * 100.0))
