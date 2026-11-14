from datetime import date, datetime

from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.record_gate import ROI_SCORE_SLOPE, min_picks, record_key
from app.services.auto_pick.scoring_context import ScoringContext
from app.services.mlb_hit_pick import hit_confidence_pct
from app.services.mlb_strikeout_pick import signed_edge_for_side

# "A strong edge is about this big" per market, so edge scores compare across
# markets. Hand-set scales; tune them from graded results.
EDGE_NORMALIZERS = {
    MarketType.MONEYLINE: 0.20,
    MarketType.SPREAD: 7.0,
    MarketType.TOTAL: 7.0,
    MarketType.PLAYER_PROP: 4.0,
}
SPREAD_EDGE_BY_LEAGUE = {"NBA": 7.0, "WNBA": 7.0, "NFL": 4.0}
TOTAL_EDGE_BY_LEAGUE = {"NBA": 8.0, "WNBA": 8.0, "NFL": 5.0, "NHL": 1.0, "MLB": 1.5}
PROP_EDGE_BY_STAT = {
    "points": 4.0,
    "rebounds": 2.5,
    "assists": 2.0,
    "steals": 0.8,
    "blocks": 0.8,
    "threes": 1.2,
    "pra": 6.0,
    "passing_yards": 40.0,
    "receiving_yards": 18.0,
    "rushing_yards": 18.0,
    "saves": 4.0,
    "shots_on_goal": 1.5,
    "strikeouts": 1.5,
    "hits": 0.5,
}
UNKNOWN_PROP_EDGE_FRACTION = 0.15  # of the line


def edge_normalizer(candidate: BetCandidate) -> float:
    mt = candidate.market_type
    if mt == MarketType.SPREAD:
        return SPREAD_EDGE_BY_LEAGUE.get(candidate.league, EDGE_NORMALIZERS[mt])
    if mt == MarketType.TOTAL:
        return TOTAL_EDGE_BY_LEAGUE.get(candidate.league, EDGE_NORMALIZERS[mt])
    if mt == MarketType.PLAYER_PROP:
        norm = PROP_EDGE_BY_STAT.get(candidate.projection_metadata.get("stat"))
        if norm is None:
            norm = UNKNOWN_PROP_EDGE_FRACTION * abs(candidate.market_line or 0.0)
        return norm if norm > 0 else EDGE_NORMALIZERS[mt]
    return EDGE_NORMALIZERS[mt]


def _implied(odds: float) -> float:
    return 100.0 / (odds + 100.0) if odds > 0 else -odds / (-odds + 100.0)


def raw_edge(candidate: BetCandidate) -> float:
    """Signed edge from the picked side's point of view (units of the market)."""
    md = candidate.projection_metadata
    side = (md.get("side") or "").lower()
    mt = candidate.market_type
    if mt == MarketType.SPREAD:
        margin = candidate.our_projection
        return (margin if side == "home" else -margin) + candidate.market_line
    if mt == MarketType.MONEYLINE:
        p = candidate.our_projection
        q_odds = md.get("opp_odds")
        own = _implied(candidate.market_odds)
        implied = own if q_odds is None else own / (own + _implied(q_odds))
        return p - implied
    return signed_edge_for_side(candidate.our_projection, candidate.market_line, side)


def edge_sub_score(candidate: BetCandidate) -> float:
    if candidate.projection_metadata.get("stat") == "hits":
        combined = candidate.projection_metadata.get("combined_score")
        if combined is not None:
            # Hits board combined_score maps to 0–100; boost so board 2.5+ clears pick threshold.
            return max(
                0.0,
                min(100.0, hit_confidence_pct(float(combined)) * 1.18),
            )

    delta = raw_edge(candidate)
    raw = (delta / edge_normalizer(candidate)) * 100.0
    if raw > 100.0:
        return 100.0
    if raw < -100.0:
        return -100.0
    return raw


def historical_sub_score(candidate: BetCandidate, context: ScoringContext) -> float:
    rec = context.records.get(record_key(candidate))
    if rec is not None and rec.n_eff >= min_picks():
        return max(0.0, min(100.0, 50.0 + rec.shrunk_roi * ROI_SCORE_SLOPE))
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
    sample = md.get("sample_size")
    if sample is not None:
        if sample < 5:
            score -= 45
        elif sample < 10:
            score -= 20

    gen_at = md.get("generated_at")
    if gen_at and context.now:
        try:
            if isinstance(gen_at, datetime):
                gen_dt = gen_at
            elif isinstance(gen_at, date):
                gen_dt = datetime.combine(gen_at, datetime.min.time())
            else:
                gen_dt = datetime.fromisoformat(str(gen_at))
            age_h = (context.now - gen_dt).total_seconds() / 3600.0
            if age_h > 24:
                score -= 55
            elif age_h > 12:
                score -= 15
        except (TypeError, ValueError):
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
