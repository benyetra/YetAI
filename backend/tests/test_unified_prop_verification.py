"""Unified + prop verification fixes for YetAI-placed MLB props."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.simple_unified_bet_model import BetStatus, BetType, SimpleUnifiedBet
from app.services.unified_bet_verification_service import UnifiedBetVerificationService
from app.services.player_prop_verification_service import PlayerPropVerificationService


def test_determine_sport_from_mlb_column():
    bet = MagicMock()
    bet.league = None
    bet.sport_key = None
    bet.sport = "MLB"
    assert PlayerPropVerificationService()._determine_sport_from_bet(bet) == "mlb"


def test_game_date_uses_commence_time_not_missing_attr():
    bet = MagicMock()
    bet.commence_time = datetime(2026, 5, 24, 18, 0)
    bet.yetai_bet_id = None
    bet.placed_at = datetime(2026, 5, 27, 12, 0)
    svc = PlayerPropVerificationService()
    assert svc._game_date_for_unified_prop(bet).isoformat() == "2026-05-24"


def test_unified_prop_evaluation_does_not_require_missing_self_db():
    service = UnifiedBetVerificationService()
    bet = MagicMock()
    bet.id = "bet-1234"
    bet.bet_type = BetType.PROP
    bet.amount = 100.0
    bet.potential_win = 90.0

    with patch(
        "app.services.player_prop_verification_service.PlayerPropVerificationService.verify_single_prop",
        new=AsyncMock(
            return_value={
                "status": BetStatus.LOST,
                "result_amount": 0.0,
                "reasoning": "MLB prop graded",
            }
        ),
    ):
        result = AsyncMock()
        import asyncio

        result = asyncio.run(service._evaluate_bet_outcome(bet, 0, 0))

    assert result.status == BetStatus.LOST
    assert result.reasoning == "MLB prop graded"


def test_fetch_mlb_player_stats_uses_game_date_season():
    service = PlayerPropVerificationService()
    game_date = datetime(2026, 5, 27).date()

    search_response = MagicMock()
    search_response.raise_for_status.return_value = None
    search_response.json.return_value = {"people": [{"id": 123}]}

    stats_response = MagicMock()
    stats_response.raise_for_status.return_value = None
    stats_response.json.return_value = {
        "people": [
            {
                "stats": [
                    {
                        "type": {"displayName": "gameLog"},
                        "splits": [{"date": "2026-05-27", "stat": {"strikeouts": 10}}],
                    }
                ]
            }
        ]
    }

    with patch(
        "app.services.player_prop_verification_service.requests.get",
        side_effect=[search_response, stats_response],
    ) as mock_get:
        stats = service._fetch_mlb_player_stats("Gerrit Cole", "strikeouts", game_date)

    assert stats == {"strikeouts": 10}
    assert "season=2026" in mock_get.call_args_list[1].args[0]


def test_retryable_evaluation_error_prop_is_detected():
    service = UnifiedBetVerificationService()
    bet = MagicMock()
    bet.status = BetStatus.LOST
    bet.bet_type = BetType.PROP
    bet.reasoning = "Evaluation error: missing session"
    assert service._is_retryable_evaluation_error(bet) is True


def test_extract_stat_value_reads_strikeouts_alias():
    service = PlayerPropVerificationService()
    stats = {"strikeOuts": 5, "inningsPitched": "4.1"}
    assert service._extract_stat_value(stats, "strikeouts") == 5


def test_game_date_prefers_yetai_commence_over_placement_time():
    from app.models.database_models import YetAIBet, BetType

    yetai = YetAIBet(
        id="pick-connor",
        title="Twins @ Sox",
        description="d",
        bet_type=BetType.PROP,
        selection="Connor Prielipp UNDER 5.5 strikeouts",
        odds=-110,
        confidence=80,
        commence_time=datetime(2026, 5, 27, 23, 40),
    )
    bet = MagicMock()
    bet.yetai_bet_id = None
    bet.game_id = "pick-connor"
    bet.odds_api_event_id = "pick-connor"
    bet.commence_time = datetime(2026, 5, 27, 16, 22)
    bet.placed_at = datetime(2026, 5, 27, 16, 22)

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = yetai
    svc = PlayerPropVerificationService(mock_db)
    assert svc._game_date_for_unified_prop(bet).isoformat() == "2026-05-27"


def test_non_prop_loss_is_not_retryable():
    service = UnifiedBetVerificationService()
    bet = MagicMock()
    bet.status = BetStatus.LOST
    bet.bet_type = BetType.SPREAD
    bet.reasoning = "Evaluation error: parse issue"
    assert service._is_retryable_evaluation_error(bet) is False


def test_unified_verify_settles_mlb_props_without_odds_scores():
    import asyncio

    service = UnifiedBetVerificationService()
    mock_db = MagicMock()
    prop_bet = MagicMock()
    prop_bet.id = "prop-wheeler"
    prop_bet.status = BetStatus.PENDING
    prop_bet.bet_type = BetType.PROP
    prop_bet.sport = "MLB"
    prop_bet.selection = "Zack Wheeler OVER 6.5 strikeouts"
    prop_bet.odds_api_event_id = "evt-1"
    prop_bet.game_id = "evt-1"
    prop_bet.home_team = "Philadelphia Phillies"
    prop_bet.away_team = "Los Angeles Dodgers"
    prop_bet.amount = 50.0
    prop_bet.potential_win = 68.0
    prop_bet.reasoning = None
    prop_bet.yetai_bet_id = None

    mock_db.query.return_value.filter.return_value.all.return_value = [prop_bet]
    mock_db.query.return_value.filter.return_value.first.return_value = prop_bet

    with (
        patch(
            "app.services.unified_bet_verification_service.SessionLocal",
            return_value=mock_db,
        ),
        patch.object(
            service.odds_service,
            "get_scores_optimized",
            side_effect=RuntimeError("Odds API unavailable"),
        ) as mock_scores,
        patch(
            "app.services.player_prop_verification_service.PlayerPropVerificationService.verify_single_prop",
            new=AsyncMock(
                return_value={
                    "status": BetStatus.LOST,
                    "result_amount": 0.0,
                    "reasoning": "MLB prop graded",
                }
            ),
        ),
        patch(
            "app.services.yetai_bets_service_db.YetAIBetsServiceDB.sync_yetai_from_unified_bet",
            return_value=None,
        ),
    ):
        result = asyncio.run(service.verify_all_pending_bets())

    assert result["success"] is True
    assert result["settled"] >= 1
    mock_scores.assert_not_called()
    assert prop_bet.status == BetStatus.LOST


def test_is_unified_prop_accepts_database_bet_type_enum():
    from app.models.database_models import BetType as LegacyBetType

    bet = MagicMock()
    bet.bet_type = LegacyBetType.PROP
    from app.services.player_prop_verification_service import _is_unified_prop_bet

    assert _is_unified_prop_bet(bet) is True


def test_apply_prop_settlement_updates_pending_bet():
    from app.services.player_prop_verification_service import (
        PlayerPropVerificationService,
    )

    bet = MagicMock()
    bet.id = "ab0e4476-ccbe-48c8-a72f-897d9b184b02"
    bet.status = BetStatus.PENDING
    bet.reasoning = None
    bet.amount = 50.0
    bet.potential_win = 68.0

    mock_db = MagicMock()
    with patch(
        "app.services.yetai_bets_service_db.YetAIBetsServiceDB.sync_yetai_from_unified_bet",
        return_value=None,
    ):
        ok = PlayerPropVerificationService._apply_prop_settlement(
            mock_db,
            bet,
            {
                "status": BetStatus.LOST,
                "result_amount": 0.0,
                "reasoning": "MLB prop graded",
            },
        )

    assert ok is True
    assert bet.status == BetStatus.LOST
    assert bet.settled_at is not None


def test_mlb_boxscore_fallback_when_gamelog_empty():
    service = PlayerPropVerificationService()
    bet = MagicMock()
    bet.home_team = "Los Angeles Dodgers"
    bet.away_team = "Philadelphia Phillies"
    game_date = datetime(2026, 5, 29).date()

    search_response = MagicMock()
    search_response.raise_for_status.return_value = None
    search_response.json.return_value = {"people": [{"id": 554430}]}

    empty_log = MagicMock()
    empty_log.raise_for_status.return_value = None
    empty_log.json.return_value = {"people": [{"stats": []}]}

    schedule_response = MagicMock()
    schedule_response.raise_for_status.return_value = None
    schedule_response.json.return_value = {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": 777001,
                        "teams": {
                            "home": {"team": {"name": "Los Angeles Dodgers"}},
                            "away": {"team": {"name": "Philadelphia Phillies"}},
                        },
                    }
                ]
            }
        ]
    }

    box_response = MagicMock()
    box_response.raise_for_status.return_value = None
    box_response.json.return_value = {
        "teams": {
            "home": {
                "players": {
                    "ID554430": {
                        "person": {"fullName": "Zack Wheeler"},
                        "stats": {"pitching": {"strikeOuts": 4}},
                    }
                }
            },
            "away": {"players": {}},
        }
    }

    with patch(
        "app.services.player_prop_verification_service.requests.get",
        side_effect=[
            search_response,
            empty_log,
            empty_log,
            schedule_response,
            box_response,
        ],
    ):
        stats = service._fetch_mlb_player_stats(
            "Zack Wheeler",
            "strikeouts",
            game_date,
            bet=bet,
        )

    assert service._extract_stat_value(stats, "strikeouts") == 4


def test_mlb_fetch_tries_prior_season_when_calendar_year_differs():
    service = PlayerPropVerificationService()
    game_date = datetime(2026, 5, 29).date()

    search_response = MagicMock()
    search_response.raise_for_status.return_value = None
    search_response.json.return_value = {"people": [{"id": 554430}]}

    stats_2026 = MagicMock()
    stats_2026.raise_for_status.return_value = None
    stats_2026.json.return_value = {"people": [{"stats": []}]}

    stats_2025 = MagicMock()
    stats_2025.raise_for_status.return_value = None
    stats_2025.json.return_value = {
        "people": [
            {
                "stats": [
                    {
                        "type": {"displayName": "gameLog"},
                        "splits": [
                            {
                                "date": "2025-05-29",
                                "stat": {"strikeOuts": 6},
                            }
                        ],
                    }
                ]
            }
        ]
    }

    with patch(
        "app.services.player_prop_verification_service.requests.get",
        side_effect=[search_response, stats_2026, stats_2025],
    ) as mock_get:
        stats = service._fetch_mlb_player_stats("Zack Wheeler", "strikeouts", game_date)

    assert service._extract_stat_value(stats, "strikeouts") == 6
    assert "season=2025" in mock_get.call_args_list[2].args[0]
