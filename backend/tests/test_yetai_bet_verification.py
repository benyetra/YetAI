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
    yetai_bet_is_stale,
    yetai_bet_visible_as_live,
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


def test_stale_after_game_day_even_if_created_recently():
    bet = YetAIBet(
        id="x",
        title="NBA player prop",
        description="d",
        bet_type=BetType.PROP,
        selection="Luke Kornet OVER 1.5 points",
        odds=-110,
        confidence=80,
        created_at=datetime.utcnow() - timedelta(hours=2),
        prediction_factors={"event_id": "nba-prop-2026-05-26-1-points"},
    )
    cutoff = datetime.utcnow() - timedelta(hours=24)
    assert yetai_bet_is_stale(bet, cutoff) is True


def test_stale_uses_created_at_when_no_commence_time():
    old = datetime.utcnow() - timedelta(hours=48)
    bet = YetAIBet(
        id="x",
        title="A vs B",
        description="d",
        bet_type=BetType.PROP,
        selection="Player UNDER 4.5 strikeouts",
        odds=-110,
        confidence=80,
        created_at=old,
    )
    cutoff = datetime.utcnow() - timedelta(hours=24)
    assert yetai_bet_is_stale(bet, cutoff) is True


def test_verify_queries_active_not_only_pending():
    service = YetAIBetsServiceDB()
    mock_db = MagicMock()
    active_bet = MagicMock()
    active_bet.id = "active-1"
    active_bet.status = "active"
    active_bet.bet_type = BetType.PROP
    active_bet.sport = "MLB"
    active_bet.game_id = None
    active_bet.selection = "Christian Scott UNDER 4.5 strikeouts"
    active_bet.title = "Mets @ Marlins"
    active_bet.commence_time = None
    active_bet.created_at = datetime.utcnow() - timedelta(hours=1)
    active_bet.prediction_factors = {}

    chain = mock_db.query.return_value.filter.return_value
    chain.all.return_value = [active_bet]

    with (
        patch(
            "app.services.yetai_bets_service_db.SessionLocal",
            return_value=mock_db,
        ),
        patch(
            "app.services.player_prop_verification_service.PlayerPropVerificationService"
        ) as mock_prop_cls,
    ):
        mock_prop = mock_prop_cls.return_value
        mock_prop.verify_yetai_mlb_prop.return_value = (
            "won",
            "Won: Under 4.5 — actual 2",
        )
        result = asyncio.run(service.verify_pending_yetai_bets())

    assert result["success"] is True
    assert result["settled"] == 1
    assert active_bet.status == "won"
    mock_prop.verify_yetai_mlb_prop.assert_called_once()


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


def test_verify_regrades_lost_evaluation_error_mlb_prop():
    service = YetAIBetsServiceDB()
    mock_db = MagicMock()
    lost_bet = YetAIBet(
        id="connor-pick",
        title="Twins @ Sox",
        description="d",
        bet_type=BetType.PROP,
        selection="Connor Prielipp UNDER 5.5 strikeouts",
        odds=-110,
        confidence=80,
        sport="MLB",
        status="lost",
        result="Evaluation error: missing db",
        commence_time=datetime(2026, 5, 27, 23, 40),
        created_at=datetime(2026, 5, 27, 16, 20),
    )

    chain = mock_db.query.return_value.filter.return_value
    chain.all.return_value = [lost_bet]

    with (
        patch(
            "app.services.yetai_bets_service_db.SessionLocal",
            return_value=mock_db,
        ),
        patch.object(service, "_expire_stale_pending_approval", return_value=0),
        patch(
            "app.services.player_prop_verification_service.PlayerPropVerificationService"
        ) as mock_prop_cls,
    ):
        mock_prop = mock_prop_cls.return_value
        mock_prop.verify_yetai_mlb_prop.return_value = (
            "won",
            "Won: Under 5.5 — actual 5 (Connor Prielipp)",
        )
        result = asyncio.run(service.verify_pending_yetai_bets())

    assert result["success"] is True
    assert result["settled"] == 1
    assert lost_bet.status == "won"
    mock_prop.verify_yetai_mlb_prop.assert_called_once()


def test_verify_settles_nba_prop():
    service = YetAIBetsServiceDB()
    mock_db = MagicMock()
    nba_bet = MagicMock()
    nba_bet.id = "nba-prop-1"
    nba_bet.status = "active"
    nba_bet.bet_type = BetType.PROP
    nba_bet.sport = "NBA"
    nba_bet.game_id = None
    nba_bet.selection = "Luke Kornet OVER 1.5 points"
    nba_bet.title = "NBA player prop"
    nba_bet.commence_time = None
    nba_bet.created_at = datetime(2026, 5, 28, 17, 0)
    nba_bet.prediction_factors = {"event_id": "nba-prop-2026-05-28-1-points"}
    nba_bet.home_team = None
    nba_bet.away_team = None

    chain = mock_db.query.return_value.filter.return_value
    chain.all.return_value = [nba_bet]
    chain.first.return_value = None

    with (
        patch(
            "app.services.yetai_bets_service_db.SessionLocal",
            return_value=mock_db,
        ),
        patch.object(service, "_expire_stale_pending_approval", return_value=0),
        patch(
            "app.services.player_prop_verification_service.PlayerPropVerificationService"
        ) as mock_prop_cls,
    ):
        mock_prop = mock_prop_cls.return_value
        mock_prop.verify_yetai_mlb_prop = MagicMock()
        mock_prop.verify_yetai_nba_prop.return_value = (
            "won",
            "Won: Over 1.5 — actual 8 (Luke Kornet)",
        )
        result = asyncio.run(service.verify_pending_yetai_bets())

    assert result["success"] is True
    assert result["settled"] == 1
    assert nba_bet.status == "won"
    mock_prop.verify_yetai_nba_prop.assert_called_once()


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


def test_verify_yetai_nba_prop_prefers_api_over_db():
    from app.services.player_prop_verification_service import (
        PlayerPropVerificationService,
    )

    bet = YetAIBet(
        id="nba-1",
        title="NBA player prop",
        description="d",
        bet_type=BetType.PROP,
        selection="Victor Wembanyama UNDER 27.5 points",
        odds=-110,
        confidence=80,
        sport="NBA",
        prediction_factors={"event_id": "nba-prop-2026-05-28-1-points"},
    )
    service = PlayerPropVerificationService(db=MagicMock())
    with (
        patch.object(
            service, "_fetch_nba_prop_actual_from_api", return_value=28.0
        ) as api,
        patch.object(service, "_fetch_nba_prop_actual_from_db", return_value=0.0) as db,
    ):
        outcome = service.verify_yetai_nba_prop(bet, date(2026, 5, 28))
    assert outcome[0] == "lost"
    api.assert_called_once()
    db.assert_not_called()


def test_retryable_nba_prop_regrade_recent_won_lost():
    service = YetAIBetsServiceDB()
    recent = YetAIBet(
        id="r1",
        title="NBA player prop",
        description="d",
        bet_type=BetType.PROP,
        selection="Luke Kornet OVER 1.5 points",
        odds=-110,
        confidence=80,
        sport="NBA",
        status="lost",
        settled_at=datetime.utcnow() - timedelta(hours=2),
        result="Lost: Over 1.5 — actual 1.0 (Luke Kornet)",
    )
    old = YetAIBet(
        id="r2",
        title="NBA player prop",
        description="d",
        bet_type=BetType.PROP,
        selection="Old Player OVER 10.5 points",
        odds=-110,
        confidence=80,
        sport="NBA",
        status="won",
        settled_at=datetime.utcnow() - timedelta(days=30),
    )
    assert service._is_retryable_nba_prop_regrade(recent) is True
    assert service._is_retryable_nba_prop_regrade(old) is False
