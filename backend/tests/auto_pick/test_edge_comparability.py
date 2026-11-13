"""Edge scores must be comparable across markets (per-market strong-edge scales)."""

from datetime import datetime

import pytest

from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.scorer import ConfidenceScorer
from app.services.auto_pick.scoring_context import ScoringContext, ScoringWeights
from app.services.auto_pick.sub_scores import edge_sub_score

P, S, T = MarketType.PLAYER_PROP, MarketType.SPREAD, MarketType.TOTAL

# (market, league, stat, line, edge): a comparably strong edge in each market.
STRONG = [
    (P, "NBA", "points", 24.5, 3.0),
    (P, "NBA", "rebounds", 8.5, 1.9),
    (P, "NBA", "assists", 6.5, 1.5),
    (P, "NBA", "steals", 1.5, 0.6),
    (P, "NBA", "blocks", 1.5, 0.6),
    (P, "NBA", "threes", 2.5, 0.9),
    (P, "NBA", "pra", 35.5, 4.5),
    (P, "NFL", "passing_yards", 245.5, 30.0),
    (P, "NFL", "receiving_yards", 55.5, 13.5),
    (P, "NFL", "rushing_yards", 60.5, 13.5),
    (P, "NHL", "saves", 27.5, 3.0),
    (P, "NHL", "shots_on_goal", 2.5, 1.1),
    (P, "MLB", "strikeouts", 5.5, 1.1),
    (S, "NBA", None, 0.0, 5.25),
    (S, "WNBA", None, 0.0, 5.25),
    (S, "NFL", None, 0.0, 3.0),
    (T, "NBA", None, 224.5, 6.0),
    (T, "WNBA", None, 165.5, 6.0),
    (T, "NFL", None, 45.5, 3.75),
    (T, "NHL", None, 6.0, 0.75),
    (T, "MLB", None, 8.5, 1.1),
]


def _cand(market, league, stat, line, edge):
    md = {"side": "home" if market == S else "over", "model_confidence": 0.7}
    if stat:
        md["stat"] = stat
    # Spread: line 0, projected home margin = edge. Others: projection = line + edge.
    return BetCandidate(
        market_type=market,
        league=league,
        event_id="e",
        selection="s",
        market_line=line,
        market_odds=-110,
        our_projection=edge if market == S else line + edge,
        projection_metadata=md,
    )


def _total(c):
    ctx = ScoringContext(
        weights=ScoringWeights(), score_threshold=65.0, now=datetime(2026, 5, 22)
    )
    return ConfidenceScorer().score(c, ctx).total


def test_comparable_strong_edges_score_within_ten_points():
    totals = {row[:3]: _total(_cand(*row)) for row in STRONG}
    assert max(totals.values()) - min(totals.values()) <= 10, totals
    assert all(edge_sub_score(_cand(*row)) < 100 for row in STRONG)


@pytest.mark.parametrize(
    "prop",
    [
        (P, "NFL", "receiving_yards", 55.5, 4.5),
        (P, "NFL", "passing_yards", 245.5, 12.5),
    ],
)
def test_small_yardage_edge_does_not_outscore_nba_spread(prop):
    nba_spread = _total(_cand(S, "NBA", None, 0.0, 3.5))
    assert _total(_cand(*prop)) < nba_spread


def test_nhl_total_can_qualify():
    assert _total(_cand(T, "NHL", None, 6.0, 1.0)) >= 65.0


def test_unknown_stat_uses_share_of_line():
    c = _cand(P, "NBA", "turnovers", 4.0, 0.3)  # 0.3 / (0.15 * 4.0) -> 50
    assert edge_sub_score(c) == pytest.approx(50.0)
