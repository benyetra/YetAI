"""
Backtest CLI for tuning auto-pick weights and threshold.

Replays historical odds + projections through ConfidenceScorer + BetSelector
and reports hit rates per tier, ROI, and score-vs-outcome calibration.

The two private functions (_load_historical_candidates_for, _did_win) are
intentionally stubbed: they depend on historical projection data being
persisted alongside settled YetAIBet rows. Backfill or wire up when that data
is available (see follow-up note in docs/superpowers/specs/...-design.md).
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.services.auto_pick.candidate import BetCandidate
from app.services.auto_pick.config_loader import load_scoring_config
from app.services.auto_pick.context_builder import build_scoring_context
from app.services.auto_pick.scorer import ConfidenceScorer
from app.services.auto_pick.selector import BetSelector, ScoredCandidate, SelectorConfig


@dataclass
class BacktestSummary:
    by_tier: dict
    overall_hit_rate: float | None
    calibration: dict


def run_backtest(start: date, end: date, db: Session) -> dict:
    cfg = load_scoring_config(db)
    scorer = ConfidenceScorer()
    selector = BetSelector(
        SelectorConfig(
            threshold=cfg.score_threshold,
            odds_min=cfg.odds_min,
            odds_max=cfg.odds_max,
            max_picks=cfg.max_picks,
            parlay_leg_threshold=cfg.parlay_leg_threshold,
            parlay_score_threshold=cfg.parlay_score_threshold,
        )
    )

    by_tier = {"free": [0, 0], "pro": [0, 0], "elite": [0, 0]}
    calibration: dict[int, list[int]] = {
        b: [0, 0] for b in (65, 70, 75, 80, 85, 90, 95)
    }

    cur = start
    while cur <= end:
        now = datetime.combine(cur, datetime.min.time())
        ctx = build_scoring_context(db, cfg, now)
        candidates = _load_historical_candidates_for(db, cur)
        scored = [
            ScoredCandidate(candidate=c, score=scorer.score(c, ctx)) for c in candidates
        ]
        picks = selector.select(scored)
        for p in picks:
            won = _did_win(db, p.candidate)
            tier_key = p.tier.value if p.tier else "free"
            by_tier[tier_key][1] += 1
            by_tier[tier_key][0] += int(won)
            bucket = min(95, 5 * (int(p.score.total) // 5))
            if bucket in calibration:
                calibration[bucket][1] += 1
                calibration[bucket][0] += int(won)
        cur += timedelta(days=1)

    return {
        "by_tier": {
            k: {
                "wins": v[0],
                "total": v[1],
                "hit_rate": (v[0] / v[1]) if v[1] else None,
            }
            for k, v in by_tier.items()
        },
        "overall_hit_rate": _ratio(
            [by_tier[t][0] for t in by_tier],
            [by_tier[t][1] for t in by_tier],
        ),
        "calibration": {
            str(b): {"wins": v[0], "total": v[1]} for b, v in calibration.items()
        },
    }


def _ratio(wins, totals):
    w, t = sum(wins), sum(totals)
    return (w / t) if t else None


def _load_historical_candidates_for(db: Session, d: date) -> list[BetCandidate]:
    """
    Return BetCandidate-shaped objects from settled history on date `d`.

    Requires historical projections to be persisted alongside settled YetAIBet
    rows (e.g., via score_breakdown JSON snapshots). Until that data path is
    wired, this returns an empty list — the backtest produces zero picks for
    each day until backfill exists.
    """
    return []


def _did_win(db: Session, candidate: BetCandidate) -> bool:
    """
    Look up the actual outcome for candidate.event_id + candidate.selection in
    settled YetAIBet rows. Returns True if the bet hit.

    Currently a stub — wire up alongside _load_historical_candidates_for.
    """
    raise NotImplementedError(
        "Wire up alongside _load_historical_candidates_for once historical "
        "projection snapshots are persisted with settled bets."
    )
