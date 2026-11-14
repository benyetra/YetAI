from app.services.auto_pick.candidate import BetCandidate
from app.services.auto_pick.confidence_score import ConfidenceScore
from app.services.auto_pick.record_gate import (
    key_label,
    min_picks,
    record_key,
    window_days,
)
from app.services.auto_pick.scoring_context import ScoringContext
from app.services.auto_pick.sub_scores import (
    edge_sub_score,
    freshness_sub_score,
    historical_sub_score,
    line_movement_sub_score,
    model_confidence_sub_score,
    odds_sanity_sub_score,
    raw_edge,
)


class ConfidenceScorer:
    def score(
        self, candidate: BetCandidate, context: ScoringContext
    ) -> ConfidenceScore:
        breakdown = {
            "edge": edge_sub_score(candidate),
            "historical": historical_sub_score(candidate, context),
            "freshness": freshness_sub_score(candidate, context),
            "line_movement": line_movement_sub_score(candidate, context),
            "odds_sanity": odds_sanity_sub_score(candidate, context),
            "model_conf": model_confidence_sub_score(candidate),
        }
        w = context.weights
        total = (
            breakdown["edge"] * w.edge
            + breakdown["historical"] * w.historical
            + breakdown["freshness"] * w.freshness
            + breakdown["line_movement"] * w.line_movement
            + breakdown["odds_sanity"] * w.odds_sanity
            + breakdown["model_conf"] * w.model_conf
        )
        reasoning = self._build_reasoning(candidate, breakdown, context)
        return ConfidenceScore(
            total=round(total, 2), breakdown=breakdown, reasoning=reasoning
        )

    def _build_reasoning(self, c: BetCandidate, b: dict, ctx: ScoringContext) -> str:
        delta = raw_edge(c)
        sign = "+" if delta >= 0 else ""
        parts = [
            f"{c.selection}: projection {c.our_projection} vs line {c.market_line} (edge {sign}{delta:.2f}).",
            f"Edge {b['edge']:.0f}, historical {b['historical']:.0f}, freshness {b['freshness']:.0f}.",
        ]
        rec = ctx.records.get(record_key(c))
        hist = ctx.historical_hit_rates.get((c.market_type.value, c.league))
        if rec is not None and rec.n_eff >= min_picks():
            parts.append(
                f"{key_label(rec.key)} L{window_days()}d record {rec.n_eff:.0f} picks, "
                f"shrunk ROI {rec.shrunk_roi*100:+.1f}%."
            )
        elif hist is not None:
            parts.append(
                f"{c.market_type.value} {c.league} L90d hit rate {hist*100:.0f}%."
            )
        if b["line_movement"] != 50.0:
            parts.append(
                f"Line movement: {'with us' if b['line_movement'] > 50 else 'against us'}."
            )
        return " ".join(parts)
