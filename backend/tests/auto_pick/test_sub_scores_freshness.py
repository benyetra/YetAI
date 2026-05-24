from datetime import date, datetime, timedelta

from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.scoring_context import ScoringContext, ScoringWeights
from app.services.auto_pick.sub_scores import freshness_sub_score


NOW = datetime(2026, 5, 22, 9, 0, 0)


def _ctx():
    return ScoringContext(weights=ScoringWeights(), score_threshold=65.0, now=NOW)


def _cand(metadata):
    return BetCandidate(
        market_type=MarketType.PLAYER_PROP,
        league="MLB",
        event_id="e",
        selection="s",
        market_line=0,
        market_odds=-110,
        our_projection=0,
        projection_metadata=metadata,
    )


def test_freshness_full_when_recent_large_sample_no_flags():
    md = {
        "sample_size": 30,
        "generated_at": (NOW - timedelta(hours=1)).isoformat(),
        "injury_flag": False,
    }
    assert freshness_sub_score(_cand(md), _ctx()) >= 90


def test_freshness_penalty_for_small_sample():
    md = {"sample_size": 3, "generated_at": NOW.isoformat()}
    assert freshness_sub_score(_cand(md), _ctx()) < 60


def test_freshness_penalty_for_stale_projection():
    md = {"sample_size": 30, "generated_at": (NOW - timedelta(hours=48)).isoformat()}
    assert freshness_sub_score(_cand(md), _ctx()) < 50


def test_freshness_hard_penalty_on_injury_flag():
    md = {"sample_size": 30, "generated_at": NOW.isoformat(), "injury_flag": True}
    assert freshness_sub_score(_cand(md), _ctx()) < 30


def test_freshness_none_sample_size_defaults_to_neutral():
    md = {"sample_size": None, "generated_at": NOW.isoformat()}
    assert freshness_sub_score(_cand(md), _ctx()) >= 90


def test_freshness_accepts_date_object_generated_at():
    md = {"sample_size": 30, "generated_at": NOW.date()}
    assert freshness_sub_score(_cand(md), _ctx()) >= 90
