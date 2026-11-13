from datetime import date, datetime, timedelta

from app.models.database_models import SubscriptionTier
from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.confidence_score import ConfidenceScore
from app.services.auto_pick.selector import (
    BetSelector,
    ScoredCandidate,
    SelectorConfig,
    hard_gate_reason,
)

NOW = datetime(2026, 5, 22, 15, 0)  # 11:00 ET


def _sc(
    event_id,
    total,
    market_type=MarketType.PLAYER_PROP,
    odds=-110,
    league="MLB",
    selection="s",
    **kw,
):
    meta = {"side": "over"}
    meta.update(kw.pop("meta", {}))
    c = BetCandidate(
        market_type=market_type,
        league=league,
        event_id=event_id,
        selection=selection,
        market_line=5.5,
        market_odds=odds,
        our_projection=8.0,
        projection_metadata=meta,
        **kw,
    )
    return ScoredCandidate(
        candidate=c, score=ConfidenceScore(total=total, breakdown={}, reasoning="")
    )


def _reasons(scored):
    return {s.candidate.event_id: s.drop_reason for s in scored}


def test_below_threshold_with_nothing_over_floor_picks_none():
    sel = BetSelector(SelectorConfig(threshold=65.0))
    scored = [_sc("e1", 50), _sc("e2", 54.9)]
    assert sel.select(scored) == []
    assert _reasons(scored) == {"e1": "below_floor", "e2": "below_floor"}


def test_picks_top_n_by_score_capped_at_three():
    sel = BetSelector(SelectorConfig(threshold=65.0, max_picks=3, max_per_market=9))
    scored = [_sc("e1", 70), _sc("e2", 90), _sc("e3", 80), _sc("e4", 66), _sc("e5", 95)]
    picks = sel.select(scored)
    assert [p.candidate.event_id for p in picks] == ["e5", "e2", "e3"]
    assert _reasons(scored)["e1"] == "cap_reached"


def test_one_pick_per_game():
    sel = BetSelector(SelectorConfig(threshold=65.0))
    scored = [_sc("e1", 90), _sc("e1", 88), _sc("e2", 70)]
    picks = sel.select(scored)
    assert [p.candidate.event_id for p in picks] == ["e1", "e2"]
    assert scored[1].drop_reason == "same_event"


def test_game_identity_uses_teams_not_event_id():
    kw = dict(game_date=date(2026, 5, 22), home_team="A", away_team="B")
    sel = BetSelector(SelectorConfig(threshold=65.0))
    picks = sel.select([_sc("x1", 90, **kw), _sc("x2", 88, **kw)])
    assert len(picks) == 1


def test_fill_to_two_uses_floor():
    sel = BetSelector(SelectorConfig(threshold=65.0, min_score=55.0))
    scored = [_sc("e1", 80), _sc("e2", 60), _sc("e3", 58), _sc("e4", 50)]
    picks = sel.select(scored)
    assert [p.candidate.event_id for p in picks] == ["e1", "e2"]
    assert _reasons(scored)["e3"] == "below_threshold"
    assert _reasons(scored)["e4"] == "below_floor"


def test_fill_counts_already_published():
    sel = BetSelector(SelectorConfig(threshold=65.0, min_score=55.0))
    # One already live today: only one more fill needed.
    picks = sel.select([_sc("e1", 60), _sc("e2", 58)], remaining=2, already_published=1)
    assert [p.candidate.event_id for p in picks] == ["e1"]


def test_never_pads_below_floor():
    sel = BetSelector(SelectorConfig(threshold=65.0, min_score=55.0))
    assert sel.select([_sc("e1", 54), _sc("e2", 40)]) == []


def test_remaining_zero_picks_nothing():
    sel = BetSelector(SelectorConfig(threshold=65.0))
    assert sel.select([_sc("e1", 99)], remaining=0, already_published=3) == []


def test_used_games_excluded():
    sel = BetSelector(SelectorConfig(threshold=65.0))
    sc = _sc("e1", 99)
    assert sel.select([sc], used_games={("event", "e1")}) == []


def test_tier_assignment_continues_from_published_count():
    sel = BetSelector(SelectorConfig(threshold=65.0, max_picks=3, max_per_market=9))
    picks = sel.select([_sc("e1", 95), _sc("e2", 90), _sc("e3", 85)])
    assert [p.tier for p in picks] == [
        SubscriptionTier.FREE,
        SubscriptionTier.PRO,
        SubscriptionTier.PRO,
    ]
    later = sel.select([_sc("e4", 95)], remaining=1, already_published=2)
    assert later[0].tier == SubscriptionTier.PRO


def test_at_most_two_per_league_and_market():
    sel = BetSelector(SelectorConfig(threshold=65.0, max_picks=3))
    scored = [
        _sc("e1", 95, league="NBA"),
        _sc("e2", 92, league="NBA"),
        _sc("e3", 90, league="NBA"),
        _sc("e4", 70, league="NBA", market_type=MarketType.SPREAD),
    ]
    picks = sel.select(scored)
    assert [p.candidate.event_id for p in picks] == ["e1", "e2", "e4"]
    assert _reasons(scored)["e3"] == "market_concentration"


def test_market_concentration_counts_earlier_runs():
    sel = BetSelector(SelectorConfig(threshold=65.0, max_picks=3))
    scored = [_sc("e1", 95, league="NBA"), _sc("e2", 70, league="NHL")]
    picks = sel.select(
        scored,
        remaining=2,
        already_published=1,
        market_counts={("NBA", "player_prop"): 2},
    )
    assert [p.candidate.event_id for p in picks] == ["e2"]
    assert _reasons(scored)["e1"] == "market_concentration"


def test_fill_floor_off_skips_floor_fill():
    sel = BetSelector(SelectorConfig(threshold=65.0, min_score=55.0))
    scored = [_sc("e1", 80, league="NBA"), _sc("e2", 60, league="NHL")]
    picks = sel.select(scored, fill_floor=False)
    assert [p.candidate.event_id for p in picks] == ["e1"]
    assert _reasons(scored)["e2"] == "below_threshold"


# --- hard gates -------------------------------------------------------------


def _gate(sc, now=NOW):
    return hard_gate_reason(sc, now, -300, 400)


def test_gate_passes_clean_candidate():
    assert _gate(_sc("e", 70, commence_time=NOW + timedelta(hours=3))) is None


def test_gate_no_play():
    assert _gate(_sc("e", 70, meta={"side": None})) == "no_play"
    assert _gate(_sc("e", 70, meta={"side": "push"})) == "no_play"


def test_gate_non_positive_edge():
    sc = _sc("e", 70, meta={"side": "under"})  # projection 8.0 over line 5.5
    assert _gate(sc) == "non_positive_edge"


def test_gate_odds_out_of_bounds():
    assert _gate(_sc("e", 70, odds=-350)) == "odds_out_of_bounds"
    assert _gate(_sc("e", 70, odds=450)) == "odds_out_of_bounds"


def test_gate_injury_flag():
    assert _gate(_sc("e", 70, meta={"injury_flag": True})) == "injury_flag"


def test_gate_started_or_starting():
    assert (
        _gate(_sc("e", 70, commence_time=NOW - timedelta(minutes=5)))
        == "started_or_starting"
    )
    assert (
        _gate(_sc("e", 70, commence_time=NOW + timedelta(minutes=19)))
        == "started_or_starting"
    )
    assert _gate(_sc("e", 70, commence_time=NOW + timedelta(minutes=21))) is None


def test_gate_unknown_start_after_noon_et():
    sc = _sc("e", 70)
    assert _gate(sc, now=datetime(2026, 5, 22, 15, 59)) is None  # 11:59 ET
    assert _gate(sc, now=datetime(2026, 5, 22, 16, 0)) == "start_time_unknown"
