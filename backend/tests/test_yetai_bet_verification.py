"""YetAI bet verification: status scope, game-date inference, stale detection."""

import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

from app.models.database_models import YetAIBet, BetType
from app.services.yetai_bets_service_db import (
    YETAI_UNSETTLED_STATUSES,
    YetAIBetsServiceDB,
    clamp_yetai_result,
    game_date_for_yetai_bet,
    yetai_bet_subscriber_live_visible,
    yetai_bet_visible_as_live,
    yetai_pick_gradeable,
)


def test_clamp_yetai_result_truncates_long_notes():
    long = "Auto-expired: unsettled >24h without verifiable result"
    assert len(long) > 50
    assert len(clamp_yetai_result(long)) == 50
    assert clamp_yetai_result(long).endswith("...")


def test_unsettled_statuses_include_active():
    assert "active" in YETAI_UNSETTLED_STATUSES
    assert "pending" in YETAI_UNSETTLED_STATUSES


def test_game_date_from_event_id():
    bet = YetAIBet(
        id="x",
        title="A vs B",
        description="d",
        bet_type=BetType.PROP,
        selection="Player UNDER 4.5 strikeouts",
        odds=-110,
        confidence=80,
        prediction_factors={"event_id": "mlb-prop-2026-05-24-12345-strikeouts"},
    )
    assert game_date_for_yetai_bet(bet) == date(2026, 5, 24)


def test_game_date_prefers_commence_time():
    bet = YetAIBet(
        id="x",
        title="A vs B",
        description="d",
        bet_type=BetType.PROP,
        selection="Player UNDER 4.5 strikeouts",
        odds=-110,
        confidence=80,
        commence_time=datetime(2026, 5, 25, 18, 0),
        prediction_factors={"event_id": "mlb-prop-2026-05-24-12345-strikeouts"},
    )
    assert game_date_for_yetai_bet(bet) == date(2026, 5, 25)


def test_game_date_from_nba_prop_event_id():
    bet = YetAIBet(
        id="x",
        title="NBA player prop",
        description="d",
        bet_type=BetType.PROP,
        selection="Luke Kornet OVER 1.5 points",
        odds=-110,
        confidence=80,
        prediction_factors={"event_id": "nba-prop-2026-05-28-12345-points"},
    )
    assert game_date_for_yetai_bet(bet) == date(2026, 5, 28)


def test_live_visibility_ends_after_game_day_buffer():
    bet = YetAIBet(
        id="x",
        title="NBA player prop",
        description="d",
        bet_type=BetType.PROP,
        selection="Luke Kornet OVER 1.5 points",
        odds=-110,
        confidence=80,
        created_at=datetime(2026, 5, 28, 17, 0),
        prediction_factors={"event_id": "nba-prop-2026-05-28-1-points"},
    )
    still_live = datetime(2026, 5, 29, 6, 0)
    assert yetai_bet_visible_as_live(bet, now=still_live) is True
    after_window = datetime(2026, 5, 29, 12, 0)
    assert yetai_bet_visible_as_live(bet, now=after_window) is False


def test_is_parlay_bet_ignores_magicmock_parlay_legs():
    service = YetAIBetsServiceDB()
    mock_bet = MagicMock()
    mock_bet.bet_type = BetType.PROP
    assert service._is_parlay_bet(mock_bet) is False


def test_is_parlay_bet_true_for_json_legs():
    service = YetAIBetsServiceDB()
    bet = YetAIBet(
        id="p1",
        title="Parlay",
        description="d",
        bet_type=BetType.PROP,
        selection="2-Leg Parlay",
        odds=250,
        confidence=80,
        parlay_legs=[{"pick": "Leg 1"}, {"pick": "Leg 2"}],
    )
    assert service._is_parlay_bet(bet) is True


def test_lost_evaluation_error_mlb_prop_is_retryable():
    service = YetAIBetsServiceDB()
    bet = YetAIBet(
        id="x",
        title="A @ B",
        description="d",
        bet_type=BetType.PROP,
        selection="Connor Prielipp UNDER 5.5 strikeouts",
        odds=-110,
        confidence=80,
        sport="MLB",
        status="lost",
        result="Evaluation error: UnifiedBetVerificationService...",
    )
    assert service._is_retryable_error_loss(bet) is True


def test_lost_evaluation_error_baseball_mlb_is_retryable():
    service = YetAIBetsServiceDB()
    bet = YetAIBet(
        id="y",
        title="A @ B",
        description="d",
        bet_type=BetType.PROP,
        selection="Pitcher UNDER 5.5 strikeouts",
        odds=-110,
        confidence=80,
        sport="baseball_mlb",
        status="lost",
        result="Evaluation error: timeout",
    )
    assert service._is_retryable_error_loss(bet) is True


def test_subscriber_live_hides_old_parlay_but_keeps_recent_slate_props():
    old_parlay = YetAIBet(
        id="old-parlay",
        title="WNBA Freaky Friday",
        description="d",
        bet_type=BetType.PARLAY,
        selection="2-Team Parlay",
        odds=241,
        confidence=84,
        status="pending",
        commence_time=datetime(2026, 6, 6, 2, 0),
        created_at=datetime(2026, 6, 5, 21, 49),
    )
    recent_prop = YetAIBet(
        id="recent-prop",
        title="NBA player prop",
        description="d",
        bet_type=BetType.PROP,
        selection="Luke Kornet OVER 1.5 points",
        odds=-110,
        confidence=80,
        status="active",
        created_at=datetime(2026, 6, 9, 17, 0),
        prediction_factors={"event_id": "nba-prop-2026-06-09-1-points"},
    )
    now = datetime(2026, 6, 10, 17, 0)
    assert yetai_bet_subscriber_live_visible(old_parlay, now=now) is False
    assert yetai_bet_subscriber_live_visible(recent_prop, now=now) is True


def test_yetai_pick_not_gradeable_before_game_window():
    bet = YetAIBet(
        id="future",
        title="MLB prop",
        description="d",
        bet_type=BetType.PROP,
        selection="Gerrit Cole UNDER 5.5 strikeouts",
        odds=-110,
        confidence=80,
        commence_time=datetime(2026, 6, 10, 23, 0),
        created_at=datetime(2026, 6, 10, 17, 0),
    )
    assert yetai_pick_gradeable(bet, now=datetime(2026, 6, 10, 18, 0)) is False
    assert yetai_pick_gradeable(bet, now=datetime(2026, 6, 11, 3, 0)) is True


def test_yetai_pick_without_tipoff_waits_extra_calendar_day():
    bet = YetAIBet(
        id="nba-slate",
        title="NBA player prop",
        description="d",
        bet_type=BetType.PROP,
        selection="Keldon Johnson OVER 6.5 points",
        odds=-110,
        confidence=80,
        commence_time=None,
        created_at=datetime(2026, 6, 9, 17, 0),
        prediction_factors={"event_id": "nba-prop-2026-06-09-1-points"},
    )
    assert yetai_pick_gradeable(bet, now=datetime(2026, 6, 10, 17, 10)) is False
    assert yetai_pick_gradeable(bet, now=datetime(2026, 6, 11, 7, 0)) is True


def test_yetai_auto_grade_hold_blocks_grading():
    from app.services.yetai_bets_service_db import (
        set_yetai_auto_grade_hold,
        yetai_auto_grade_held,
    )

    bet = YetAIBet(
        id="held",
        title="NBA player prop",
        description="d",
        bet_type=BetType.PROP,
        selection="Luke Kornet OVER 1.5 points",
        odds=-110,
        confidence=80,
        commence_time=datetime(2026, 6, 9, 23, 0),
        created_at=datetime(2026, 6, 9, 17, 0),
    )
    set_yetai_auto_grade_hold(bet, held=True)
    assert yetai_auto_grade_held(bet)
    assert yetai_pick_gradeable(bet, now=datetime(2026, 6, 10, 20, 0)) is False


def test_retryable_error_allows_evaluation_prefix_variants():
    service = YetAIBetsServiceDB()
    bet = YetAIBet(
        id="z",
        title="A @ B",
        description="d",
        bet_type=BetType.PROP,
        selection="Pitcher UNDER 5.5 strikeouts",
        odds=-110,
        confidence=80,
        sport="MLB",
        status="lost",
        result="Evaluation failed: timeout",
    )
    assert service._is_retryable_error_loss(bet) is True


def test_nba_boxscore_uses_pts_not_pf_column():
    from app.services.player_prop_verification_service import (
        _nba_boxscore_row_to_stats,
        _nba_player_names_match,
        PlayerPropVerificationService,
    )

    headers = [
        "GAME_ID",
        "TEAM_ID",
        "TEAM_ABBREVIATION",
        "TEAM_CITY",
        "PLAYER_ID",
        "PLAYER_NAME",
        "NICKNAME",
        "START_POSITION",
        "COMMENT",
        "MIN",
        "FGM",
        "FGA",
        "FG_PCT",
        "FG3M",
        "FG3A",
        "FG3_PCT",
        "FTM",
        "FTA",
        "FT_PCT",
        "OREB",
        "DREB",
        "REB",
        "AST",
        "STL",
        "BLK",
        "TO",
        "PF",
        "PTS",
        "PLUS_MINUS",
    ]
    row = [None] * len(headers)
    name_idx = headers.index("PLAYER_NAME")
    pf_idx = headers.index("PF")
    pts_idx = headers.index("PTS")
    row[name_idx] = "Luke Kornet"
    row[pf_idx] = 1
    row[pts_idx] = 3
    stats = _nba_boxscore_row_to_stats(dict(zip(headers, row)))
    assert stats["PTS"] == 3.0
    assert stats["PTS"] != row[pf_idx]
    assert _nba_player_names_match("Luke Kornet", "Luke Kornet")
    assert not _nba_player_names_match("Victor Wembanyama", "Victor Oladipo")

    service = PlayerPropVerificationService()
    games = [[None, None, "0022400001"]]

    class FakeBox:
        def __init__(self, *args, **kwargs):
            pass

        @property
        def player_stats(self):
            return self

        def get_dict(self):
            return {"headers": headers, "data": [row]}

    with patch(
        "nba_api.stats.endpoints.boxscoretraditionalv2.BoxScoreTraditionalV2",
        FakeBox,
    ):
        found = service._find_nba_player_stats(games, "Luke Kornet", "PTS")
    assert found["PTS"] == 3.0
