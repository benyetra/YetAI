"""
Player Prop Verification Service

Automatically verifies and settles player prop bets using sport-specific stats APIs:
- MLB: MLB Stats API for pitcher/batter stats
- NFL: nfl_data_py for player stats
- NHL: NHL API for skater/goalie stats
- NBA: nba_api for player stats

This service should run daily to check previous day's completed games.
"""

import asyncio
import logging
import re
import requests
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.core.database import SessionLocal
from app.models.database_models import Bet, BetStatus, BetType, YetAIBet
from app.models.simple_unified_bet_model import (
    BetStatus as UnifiedBetStatus,
    BetType as UnifiedBetType,
    SimpleUnifiedBet,
)
from app.services.websocket_manager import manager as websocket_manager

logger = logging.getLogger(__name__)

# BoxScoreTraditionalV2 player_stats column order (nba_api); PTS is index 27, not 26.
_NBA_BOXSCORE_STAT_KEYS = ("PTS", "REB", "AST", "STL", "BLK", "FG3M")


def _normalize_player_name(name: str) -> str:
    """Lowercase, collapse whitespace, strip accents for matching."""
    import unicodedata

    cleaned = unicodedata.normalize("NFKD", (name or "").strip())
    ascii_name = cleaned.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_name.lower().split())


def _nba_player_names_match(requested: str, box_name: str) -> bool:
    """Match full name or same first token + last name (avoids 'Victor' ⊂ wrong player)."""
    req = _normalize_player_name(requested)
    box = _normalize_player_name(box_name)
    if not req or not box:
        return False
    if req == box:
        return True
    req_parts = req.split()
    box_parts = box.split()
    if len(req_parts) < 2 or len(box_parts) < 2:
        return False
    if req_parts[-1] != box_parts[-1]:
        return False
    req_first, box_first = req_parts[0], box_parts[0]
    return (
        req_first == box_first
        or box_first.startswith(req_first)
        or req_first.startswith(box_first)
    )


def _bet_type_value(bet_type) -> str:
    if bet_type is None:
        return ""
    return str(getattr(bet_type, "value", bet_type)).lower()


def _is_unified_prop_bet(bet) -> bool:
    return _bet_type_value(getattr(bet, "bet_type", None)) == UnifiedBetType.PROP.value


def _coerce_unified_status(status) -> UnifiedBetStatus:
    if isinstance(status, UnifiedBetStatus):
        return status
    raw = getattr(status, "value", status)
    return UnifiedBetStatus(str(raw).lower())


def _normalize_team_token(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _mlb_team_names_match(stored: str, api_name: str) -> bool:
    a = _normalize_team_token(stored)
    b = _normalize_team_token(api_name)
    if not a or not b:
        return False
    return a in b or b in a or a.split()[-1] == b.split()[-1]


def _nba_boxscore_row_to_stats(record: Dict) -> Dict:
    """Extract stat fields from a box score row dict."""
    stats: Dict = {}
    for key in _NBA_BOXSCORE_STAT_KEYS:
        value = record.get(key)
        if value is not None and value != "":
            try:
                stats[key] = float(value)
            except (TypeError, ValueError):
                continue
    return stats


class PlayerPropVerificationService:
    """Service for verifying player prop bets using sport-specific stats APIs"""

    def __init__(self, db: Optional[Session] = None):
        self.session = db
        self.db = db

    @staticmethod
    def _apply_prop_settlement(
        db: Session, bet: SimpleUnifiedBet, prop_result: Dict
    ) -> bool:
        """Persist a graded prop on the bet row (avoids enum/session mismatches)."""
        from app.services.yetai_bets_service_db import YetAIBetsServiceDB

        status = _coerce_unified_status(prop_result["status"])
        if status == UnifiedBetStatus.PENDING:
            return False

        bet.status = status
        bet.result_amount = float(prop_result.get("result_amount", 0.0) or 0.0)
        reasoning = prop_result.get("reasoning")
        if reasoning:
            bet.reasoning = str(reasoning)
        bet.settled_at = datetime.now(timezone.utc)
        YetAIBetsServiceDB().sync_yetai_from_unified_bet(db, bet)
        logger.info(
            "Settled prop %s: %s — %s",
            bet.id[:8],
            status.value,
            (bet.reasoning or "")[:120],
        )
        return True

    async def verify_single_prop(self, bet: SimpleUnifiedBet) -> Optional[Dict]:
        """
        Verify a single prop bet immediately (used by unified verification service)

        Args:
            bet: SimpleUnifiedBet instance with prop bet

        Returns:
            Dict with status, result_amount, reasoning if verified, None otherwise
        """
        if not bet or not _is_unified_prop_bet(bet):
            logger.debug(
                "Skipping non-prop bet %s (bet_type=%r)",
                getattr(bet, "id", "?")[:8],
                getattr(bet, "bet_type", None),
            )
            return None

        # Ensure we have a database session
        if not self.session:
            self.session = SessionLocal()

        try:
            sport = self._determine_sport_from_bet(bet)
            if not sport:
                logger.warning(
                    "Could not determine sport for prop %s (sport=%r)",
                    bet.id[:8],
                    getattr(bet, "sport", None),
                )
                return None

            game_date = self._game_date_for_unified_prop(bet)

            # Verify based on sport
            if sport == "mlb":
                result = await self._verify_single_mlb_prop(bet, game_date)
            elif sport == "nfl":
                result = await self._verify_single_nfl_prop(bet, game_date)
            elif sport == "nhl":
                result = await self._verify_single_nhl_prop(bet, game_date)
            elif sport == "nba":
                result = await self._verify_single_nba_prop(bet, game_date)
            else:
                logger.warning(f"Unsupported sport for prop verification: {sport}")
                return None

            if result is None:
                logger.info(
                    "Prop %s (%s) not gradable yet on %s",
                    bet.id[:8],
                    bet.selection[:60],
                    sport,
                )
            return result

        except Exception as e:
            logger.error(
                f"Error verifying single prop {bet.id[:8]}: {e}", exc_info=True
            )
            return None

    def _determine_sport_from_bet(self, bet: SimpleUnifiedBet) -> Optional[str]:
        """Determine sport from sport_key or sport column."""
        league = (getattr(bet, "league", None) or "").lower()
        sport_key = (getattr(bet, "sport_key", None) or "").lower()
        sport = (bet.sport or "").lower()

        blob = " ".join((league, sport_key, sport))
        if "mlb" in blob or "baseball" in blob:
            return "mlb"
        if "nfl" in blob or "americanfootball_nfl" in blob or "football_nfl" in blob:
            return "nfl"
        if "nhl" in blob or "icehockey" in blob or "hockey" in blob:
            return "nhl"
        if "nba" in blob or "basketball" in blob:
            return "nba"

        return None

    def _resolve_yetai_pick(self, bet: SimpleUnifiedBet) -> Optional[YetAIBet]:
        """Find linked YetAI pick from yetai_bet_id or legacy UUID game/event ids."""
        if not self.session:
            return None

        from app.models.database_models import YetAIBet

        if bet.yetai_bet_id:
            yetai = (
                self.session.query(YetAIBet)
                .filter(YetAIBet.id == bet.yetai_bet_id)
                .first()
            )
            if yetai:
                return yetai

        for raw_id in (
            getattr(bet, "game_id", None),
            getattr(bet, "odds_api_event_id", None),
        ):
            if not raw_id:
                continue
            candidate_id = str(raw_id)
            if candidate_id.startswith("yetai-pick-"):
                candidate_id = candidate_id[len("yetai-pick-") :]
            yetai = (
                self.session.query(YetAIBet).filter(YetAIBet.id == candidate_id).first()
            )
            if yetai:
                return yetai

        return None

    @staticmethod
    def _extract_stat_value(stats: Dict, stat_type: str):
        """Read MLB stat values with API key aliases (e.g. strikeOuts vs strikeouts)."""
        if not stats:
            return None

        direct = stats.get(stat_type)
        if direct is not None:
            return direct

        aliases = {
            "strikeouts": ("strikeOuts", "strikeouts"),
            "earnedruns": ("earnedRuns", "earnedRuns"),
            "totalbases": ("totalBases", "totalBases"),
            "home runs": ("homeRuns", "homeRuns"),
        }
        for alias in aliases.get(stat_type.lower(), ()):
            if alias in stats:
                return stats[alias]

        target = stat_type.lower()
        for key, value in stats.items():
            if key.lower() == target:
                return value

        return None

    def _game_date_for_yetai_pick(self, yetai: YetAIBet):
        import re

        if yetai.commence_time:
            return yetai.commence_time.date()

        factors = (
            yetai.prediction_factors
            if isinstance(yetai.prediction_factors, dict)
            else {}
        )
        event_id = str(factors.get("event_id") or "")
        match = re.search(r"(\d{4}-\d{2}-\d{2})", event_id)
        if match:
            from datetime import date as date_cls

            return date_cls.fromisoformat(match.group(1))
        if yetai.created_at:
            return yetai.created_at.date()
        return datetime.utcnow().date()

    def _game_date_for_unified_prop(self, bet: SimpleUnifiedBet):
        """Resolve stat lookup date for a placed prop (YetAI-linked or straight)."""
        return self._game_date_candidates_for_unified_prop(bet)[0]

    def _game_date_candidates_for_unified_prop(
        self, bet: SimpleUnifiedBet
    ) -> List[date]:
        """Dates to try when matching MLB/NBA game logs (placement vs game day)."""
        candidates: List[date] = []
        yetai = self._resolve_yetai_pick(bet)
        if yetai:
            candidates.append(self._game_date_for_yetai_pick(yetai))

        for dt in (
            getattr(bet, "commence_time", None),
            getattr(bet, "placed_at", None),
        ):
            if dt:
                candidates.append(dt.date())

        today = datetime.now(timezone.utc).date()
        candidates.append(today)
        candidates.append(today - timedelta(days=1))

        unique: List[date] = []
        for d in candidates:
            if d not in unique:
                unique.append(d)
        return unique

    @staticmethod
    def _mlb_season_candidates(game_date: date) -> List[int]:
        """MLB Stats API season labels to try (handles year skew vs game_date)."""
        seasons = [game_date.year, game_date.year - 1]
        out: List[int] = []
        for s in seasons:
            if s not in out:
                out.append(s)
        return out

    @staticmethod
    def _align_date_to_mlb_season(game_date: date, season: int) -> date:
        """Map app calendar date to the season year used in MLB game logs."""
        try:
            return game_date.replace(year=season)
        except ValueError:
            return game_date.replace(year=season, day=28)

    async def _verify_single_mlb_prop(
        self, bet: SimpleUnifiedBet, game_date
    ) -> Optional[Dict]:
        """Verify a single MLB prop bet"""
        try:
            prop_details = self._parse_mlb_prop(bet.selection)
            if not prop_details:
                return None

            stats = None
            for candidate_date in self._game_date_candidates_for_unified_prop(bet):
                stats = self._fetch_mlb_player_stats(
                    prop_details["player_name"],
                    prop_details["stat_type"],
                    candidate_date,
                    bet=bet,
                    is_pitching=prop_details.get("is_pitching", False),
                )
                if stats is not None:
                    break
            if stats is None:
                return None

            actual_value = self._extract_stat_value(stats, prop_details["stat_type"])
            if actual_value is None:
                return None

            line_value = prop_details["line_value"]
            is_over = prop_details["is_over"]
            won = self._check_prop_outcome(actual_value, line_value, is_over)

            status = UnifiedBetStatus.WON if won else UnifiedBetStatus.LOST
            result_amount = (bet.amount + bet.potential_win) if won else 0.0

            return {
                "status": status,
                "result_amount": result_amount,
                "reasoning": f"MLB prop: {prop_details['player_name']} - actual: {actual_value}, line: {line_value}",
            }
        except Exception as e:
            logger.error(f"Error verifying MLB prop: {e}")
            return None

    async def _verify_single_nfl_prop(
        self, bet: SimpleUnifiedBet, game_date
    ) -> Optional[Dict]:
        """Verify a single NFL prop bet"""
        try:
            prop_details = self._parse_nfl_prop(bet.selection)
            if not prop_details:
                return None

            stats = await self._fetch_nfl_player_stats(
                prop_details["player_name"], prop_details["stat_type"], game_date
            )
            if stats is None:
                return None

            actual_value = stats.get(prop_details["stat_type"])
            line_value = prop_details["line_value"]
            is_over = prop_details["is_over"]
            won = self._check_prop_outcome(actual_value, line_value, is_over)

            status = UnifiedBetStatus.WON if won else UnifiedBetStatus.LOST
            result_amount = (bet.amount + bet.potential_win) if won else 0.0

            return {
                "status": status,
                "result_amount": result_amount,
                "reasoning": f"NFL prop: {prop_details['player_name']} - actual: {actual_value}, line: {line_value}",
            }
        except Exception as e:
            logger.error(f"Error verifying NFL prop: {e}")
            return None

    async def _verify_single_nhl_prop(
        self, bet: SimpleUnifiedBet, game_date
    ) -> Optional[Dict]:
        """Verify a single NHL prop bet"""
        try:
            prop_details = self._parse_nhl_prop(bet.selection)
            if not prop_details:
                return None

            stats = self._fetch_nhl_player_stats(
                prop_details["player_name"], prop_details["stat_type"], game_date
            )
            if stats is None:
                return None

            actual_value = stats.get(prop_details["stat_type"])
            line_value = prop_details["line_value"]
            is_over = prop_details["is_over"]
            won = self._check_prop_outcome(actual_value, line_value, is_over)

            status = UnifiedBetStatus.WON if won else UnifiedBetStatus.LOST
            result_amount = (bet.amount + bet.potential_win) if won else 0.0

            return {
                "status": status,
                "result_amount": result_amount,
                "reasoning": f"NHL prop: {prop_details['player_name']} - actual: {actual_value}, line: {line_value}",
            }
        except Exception as e:
            logger.error(f"Error verifying NHL prop: {e}")
            return None

    async def _verify_single_nba_prop(
        self, bet: SimpleUnifiedBet, game_date
    ) -> Optional[Dict]:
        """Verify a single NBA prop bet"""
        try:
            prop_details = self._parse_nba_prop(bet.selection)
            if not prop_details:
                return None

            stats = self._fetch_nba_player_stats(
                prop_details["player_name"], prop_details["stat_type"], game_date
            )
            if stats is None:
                return None

            actual_value = stats.get(prop_details["stat_type"])
            line_value = prop_details["line_value"]
            is_over = prop_details["is_over"]
            won = self._check_prop_outcome(actual_value, line_value, is_over)

            status = UnifiedBetStatus.WON if won else UnifiedBetStatus.LOST
            result_amount = (bet.amount + bet.potential_win) if won else 0.0

            return {
                "status": status,
                "result_amount": result_amount,
                "reasoning": f"NBA prop: {prop_details['player_name']} - actual: {actual_value}, line: {line_value}",
            }
        except Exception as e:
            logger.error(f"Error verifying NBA prop: {e}")
            return None

    async def settle_pending_props_for_user(
        self, db: Session, user_id: int
    ) -> Dict[str, int]:
        """Grade this user's pending props (used when loading bet history)."""
        self.session = db
        pending = (
            db.query(SimpleUnifiedBet)
            .filter(
                SimpleUnifiedBet.user_id == user_id,
                SimpleUnifiedBet.bet_type == UnifiedBetType.PROP,
                SimpleUnifiedBet.status == UnifiedBetStatus.PENDING,
                SimpleUnifiedBet.parent_bet_id.is_(None),
            )
            .all()
        )
        if not pending:
            return {"verified": 0, "settled": 0, "errors": 0}

        settled = 0
        errors = 0
        for bet in pending:
            try:
                prop_result = await self.verify_single_prop(bet)
                if not prop_result:
                    continue
                if self._apply_prop_settlement(db, bet, prop_result):
                    settled += 1
            except Exception as e:
                errors += 1
                logger.error(
                    "Error settling pending prop %s for user %s: %s",
                    bet.id[:8],
                    user_id,
                    e,
                )

        if settled:
            db.commit()

        return {"verified": len(pending), "settled": settled, "errors": errors}

    async def verify_pending_unified_props(
        self, db: Optional[Session] = None, *, days_back: int = 14
    ) -> Dict:
        """
        Settle pending player props in simple_unified_bets via sport stats APIs.

        Complements unified bet verification (which uses Odds API for game markets).
        """
        from app.models.simple_unified_bet_model import (
            BetStatus as UnifiedBetStatus,
            BetType as UnifiedBetType,
        )

        owns_session = db is None
        if owns_session:
            db = SessionLocal()
        self.session = db

        settled = 0
        errors = 0

        try:
            cutoff = datetime.utcnow() - timedelta(days=days_back)
            pending = (
                db.query(SimpleUnifiedBet)
                .filter(
                    SimpleUnifiedBet.bet_type == UnifiedBetType.PROP,
                    SimpleUnifiedBet.status == UnifiedBetStatus.PENDING,
                    SimpleUnifiedBet.parent_bet_id.is_(None),
                    SimpleUnifiedBet.placed_at >= cutoff,
                )
                .all()
            )

            if not pending:
                return {"verified": 0, "settled": 0, "errors": 0}

            logger.info(
                "Verifying %s pending unified prop bet(s) (last %s days)",
                len(pending),
                days_back,
            )

            for bet in pending:
                try:
                    prop_result = await self.verify_single_prop(bet)
                    if not prop_result:
                        logger.info(
                            "Unified prop %s still pending (no stats): %s",
                            bet.id[:8],
                            (bet.selection or "")[:80],
                        )
                        continue
                    if self._apply_prop_settlement(db, bet, prop_result):
                        settled += 1
                except Exception as e:
                    errors += 1
                    logger.error("Error verifying unified prop %s: %s", bet.id[:8], e)

            if settled:
                db.commit()

            return {
                "verified": len(pending),
                "settled": settled,
                "errors": errors,
            }
        finally:
            if owns_session:
                db.close()
                self.session = None

    async def verify_previous_day_props(self) -> Dict:
        """
        Main entry point - verify all pending prop bets from previous day

        Returns:
            Dict with verification results
        """
        logger.info("🏈 Starting player prop verification for previous day...")

        self.session = SessionLocal()
        try:
            unified_result = await self.verify_pending_unified_props(
                self.session, days_back=14
            )

            # Get all pending prop bets from yesterday (legacy bets table)
            yesterday = datetime.utcnow().date() - timedelta(days=1)
            pending_props = self._get_pending_props(yesterday)

            if not pending_props and not unified_result.get("settled"):
                logger.info("No pending prop bets from yesterday to verify")
                return {
                    "verified": unified_result.get("verified", 0),
                    "settled": unified_result.get("settled", 0),
                    "errors": unified_result.get("errors", 0),
                }

            logger.info(f"Found {len(pending_props)} pending prop bets to verify")

            results = {
                "verified": 0,
                "settled": 0,
                "errors": 0,
                "mlb": 0,
                "nfl": 0,
                "nhl": 0,
                "nba": 0,
            }

            # Group props by sport for efficient API calls
            props_by_sport = self._group_props_by_sport(pending_props)

            # Verify each sport
            if props_by_sport.get("mlb"):
                mlb_results = await self._verify_mlb_props(
                    props_by_sport["mlb"], yesterday
                )
                results["mlb"] = mlb_results["settled"]
                results["settled"] += mlb_results["settled"]
                results["errors"] += mlb_results["errors"]

            if props_by_sport.get("nfl"):
                nfl_results = await self._verify_nfl_props(
                    props_by_sport["nfl"], yesterday
                )
                results["nfl"] = nfl_results["settled"]
                results["settled"] += nfl_results["settled"]
                results["errors"] += nfl_results["errors"]

            if props_by_sport.get("nhl"):
                nhl_results = await self._verify_nhl_props(
                    props_by_sport["nhl"], yesterday
                )
                results["nhl"] = nhl_results["settled"]
                results["settled"] += nhl_results["settled"]
                results["errors"] += nhl_results["errors"]

            if props_by_sport.get("nba"):
                nba_results = await self._verify_nba_props(
                    props_by_sport["nba"], yesterday
                )
                results["nba"] = nba_results["settled"]
                results["settled"] += nba_results["settled"]
                results["errors"] += nba_results["errors"]

            results["verified"] = len(pending_props) + unified_result.get("verified", 0)
            results["settled"] += unified_result.get("settled", 0)
            results["errors"] += unified_result.get("errors", 0)

            logger.info(
                f"✅ Prop verification complete: {results['settled']} settled, "
                f"{results['errors']} errors (MLB: {results['mlb']}, NFL: {results['nfl']}, "
                f"NHL: {results['nhl']}, NBA: {results['nba']})"
            )

            return results

        except Exception as e:
            logger.error(f"Error in prop verification: {e}", exc_info=True)
            return {"verified": 0, "settled": 0, "errors": 1}
        finally:
            if self.session:
                self.session.close()

    def _get_pending_props(self, target_date) -> List[Bet]:
        """Get all pending prop bets from a specific date"""
        start_of_day = datetime.combine(target_date, datetime.min.time())
        end_of_day = datetime.combine(target_date, datetime.max.time())

        return (
            self.session.query(Bet)
            .filter(
                and_(
                    Bet.bet_type == BetType.PROP,
                    Bet.status == BetStatus.PENDING,
                    Bet.commence_time >= start_of_day,
                    Bet.commence_time <= end_of_day,
                )
            )
            .all()
        )

    def _group_props_by_sport(self, props: List[Bet]) -> Dict[str, List[Bet]]:
        """Group prop bets by sport for batch processing"""
        grouped = {"mlb": [], "nfl": [], "nhl": [], "nba": []}

        for prop in props:
            sport = prop.sport.lower()
            if "baseball" in sport or "mlb" in sport:
                grouped["mlb"].append(prop)
            elif "football" in sport or "nfl" in sport:
                grouped["nfl"].append(prop)
            elif "hockey" in sport or "nhl" in sport:
                grouped["nhl"].append(prop)
            elif "basketball" in sport or "nba" in sport:
                grouped["nba"].append(prop)

        return grouped

    # ==================== MLB VERIFICATION ====================

    async def _verify_mlb_props(self, props: List[Bet], game_date) -> Dict:
        """Verify MLB player props using MLB Stats API"""
        logger.info(f"Verifying {len(props)} MLB prop bets...")
        settled = 0
        errors = 0

        for prop in props:
            try:
                # Parse prop details from selection
                prop_details = self._parse_mlb_prop(prop.selection)
                if not prop_details:
                    logger.warning(f"Could not parse MLB prop: {prop.selection}")
                    errors += 1
                    continue

                # Fetch player stats from MLB API
                stats = self._fetch_mlb_player_stats(
                    prop_details["player_name"],
                    prop_details["stat_type"],
                    game_date,
                    is_pitching=prop_details.get("is_pitching", False),
                )

                if stats is None:
                    logger.warning(
                        f"No MLB stats found for: {prop_details['player_name']}"
                    )
                    errors += 1
                    continue

                # Verify prop outcome
                actual_value = stats.get(prop_details["stat_type"])
                line_value = prop_details["line_value"]
                is_over = prop_details["is_over"]

                won = self._check_prop_outcome(actual_value, line_value, is_over)

                # Settle the bet
                self._settle_prop_bet(prop, won, actual_value, line_value)
                settled += 1

                logger.info(
                    f"MLB prop settled: {prop.selection} - "
                    f"{'WON' if won else 'LOST'} (actual: {actual_value}, line: {line_value})"
                )

            except Exception as e:
                logger.error(f"Error verifying MLB prop {prop.id}: {e}")
                errors += 1

        return {"settled": settled, "errors": errors}

    def _parse_mlb_prop(self, selection: str) -> Optional[Dict]:
        """
        Parse MLB prop selection string

        Examples:
        - "Yoshinobu Yamamoto under 16.5 Pitcher Outs"
        - "Aaron Judge over 1.5 Total Bases"
        """
        # Pattern: "Player Name (over|under) X.X Stat Type"
        pattern = r"(.+?)\s+(over|under)\s+([\d.]+)\s+(.+)"
        match = re.match(pattern, selection, re.IGNORECASE)

        if not match:
            return None

        player_name = match.group(1).strip()
        over_under = match.group(2).lower()
        line_value = float(match.group(3))
        stat_type = match.group(4).strip()
        stat_lower = stat_type.lower()
        pitching_labels = {"pitcher outs", "hits allowed", "earned runs"}
        is_pitching = stat_lower in pitching_labels or stat_lower == "strikeouts"

        # Map stat types to MLB API fields
        stat_mapping = {
            "pitcher outs": "outs",
            "strikeouts": "strikeouts",
            "hits": "hits",
            "hits allowed": "hits",
            "earned runs": "earnedRuns",
            "total bases": "totalBases",
            "runs": "runs",
            "rbis": "rbi",
            "home runs": "homeRuns",
        }

        stat_key = stat_mapping.get(stat_lower, stat_lower)

        return {
            "player_name": player_name,
            "stat_type": stat_key,
            "line_value": line_value,
            "is_over": over_under == "over",
            "is_pitching": is_pitching,
        }

    def _resolve_mlb_game_pk(self, bet: SimpleUnifiedBet, game_date) -> Optional[int]:
        """Find MLB gamePk from schedule using stored home/away team names."""
        if not bet.home_team or not bet.away_team:
            return None
        date_str = game_date.strftime("%Y-%m-%d")
        try:
            response = requests.get(
                "https://statsapi.mlb.com/api/v1/schedule",
                params={"sportId": 1, "date": date_str},
                timeout=15,
            )
            response.raise_for_status()
            for day in response.json().get("dates") or []:
                for game in day.get("games") or []:
                    teams = game.get("teams") or {}
                    home = (teams.get("home") or {}).get("team") or {}
                    away = (teams.get("away") or {}).get("team") or {}
                    home_name = home.get("name") or home.get("teamName") or ""
                    away_name = away.get("name") or away.get("teamName") or ""
                    normal = _mlb_team_names_match(
                        bet.home_team, home_name
                    ) and _mlb_team_names_match(bet.away_team, away_name)
                    swapped = _mlb_team_names_match(
                        bet.home_team, away_name
                    ) and _mlb_team_names_match(bet.away_team, home_name)
                    if normal or swapped:
                        return game.get("gamePk")
            return None
        except Exception as e:
            logger.warning(
                "MLB schedule lookup failed for %s @ %s on %s: %s",
                bet.away_team,
                bet.home_team,
                date_str,
                e,
            )
            return None

    def _fetch_mlb_player_stats_from_boxscore(
        self,
        bet: SimpleUnifiedBet,
        player_name: str,
        stat_type: str,
        game_date,
        *,
        is_pitching: bool = False,
    ) -> Optional[Dict]:
        """Box score fallback when game logs miss a start (common in prod)."""
        game_pk = self._resolve_mlb_game_pk(bet, game_date)
        if not game_pk:
            return None
        pitching_stats = is_pitching or stat_type.lower() in (
            "outs",
            "strikeouts",
            "earnedruns",
        )
        try:
            response = requests.get(
                f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore",
                timeout=15,
            )
            response.raise_for_status()
            box = response.json()
            players = (box.get("teams") or {}).get("home", {}).get("players") or {}
            players.update(
                (box.get("teams") or {}).get("away", {}).get("players") or {}
            )
            target = _normalize_player_name(player_name)
            for pdata in players.values():
                person = pdata.get("person") or {}
                full = person.get("fullName") or ""
                if _normalize_player_name(
                    full
                ) != target and not _nba_player_names_match(player_name, full):
                    continue
                if pitching_stats:
                    stat_payload = pdata.get("stats", {}).get("pitching") or {}
                else:
                    stat_payload = pdata.get("stats", {}).get("batting") or {}
                if stat_payload:
                    logger.info(
                        "MLB boxscore stats for %s gamePk=%s date=%s",
                        player_name,
                        game_pk,
                        game_date,
                    )
                    return stat_payload
            return None
        except Exception as e:
            logger.error(
                "MLB boxscore fetch failed gamePk=%s player=%s: %s",
                game_pk,
                player_name,
                e,
            )
            return None

    def _fetch_mlb_player_stats(
        self,
        player_name: str,
        stat_type: str,
        game_date,
        *,
        bet: Optional[SimpleUnifiedBet] = None,
        is_pitching: bool = False,
    ) -> Optional[Dict]:
        """Fetch MLB player stats from MLB Stats API (game log, then boxscore)."""
        try:
            search_url = (
                f"https://statsapi.mlb.com/api/v1/people/search?names={player_name}"
            )
            response = requests.get(search_url, timeout=15)
            response.raise_for_status()

            search_data = response.json()
            if not search_data.get("people"):
                logger.warning(
                    "MLB player search returned no match for %r", player_name
                )
                if bet:
                    return self._fetch_mlb_player_stats_from_boxscore(
                        bet,
                        player_name,
                        stat_type,
                        game_date,
                        is_pitching=is_pitching,
                    )
                return None

            player_id = search_data["people"][0]["id"]

            pitching_stats = is_pitching or stat_type.lower() in [
                "outs",
                "strikeouts",
                "earnedruns",
            ]
            target_str = game_date.strftime("%Y-%m-%d")

            for season in self._mlb_season_candidates(game_date):
                if pitching_stats:
                    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}?hydrate=stats(group=[pitching],type=[gameLog],season={season})"
                else:
                    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}?hydrate=stats(group=[hitting],type=[gameLog],season={season})"

                response = requests.get(url, timeout=15)
                response.raise_for_status()
                data = response.json()

                if "people" not in data or not data["people"]:
                    continue

                stat_blocks = data["people"][0].get("stats") or []
                game_logs = next(
                    (
                        stat["splits"]
                        for stat in stat_blocks
                        if stat.get("type", {}).get("displayName") == "gameLog"
                    ),
                    [],
                )

                aligned = self._align_date_to_mlb_season(game_date, season).strftime(
                    "%Y-%m-%d"
                )
                for game in game_logs:
                    game_date_str = (game.get("date") or "")[:10]
                    if game_date_str in (target_str, aligned):
                        stat_payload = game.get("stat")
                        if stat_payload:
                            return stat_payload

            if bet:
                return self._fetch_mlb_player_stats_from_boxscore(
                    bet,
                    player_name,
                    stat_type,
                    game_date,
                    is_pitching=is_pitching,
                )
            return None

        except Exception as e:
            logger.error(f"Error fetching MLB stats for {player_name}: {e}")
            if bet:
                return self._fetch_mlb_player_stats_from_boxscore(
                    bet,
                    player_name,
                    stat_type,
                    game_date,
                    is_pitching=is_pitching,
                )
            return None

    # ==================== NFL VERIFICATION ====================

    async def _verify_nfl_props(self, props: List[Bet], game_date) -> Dict:
        """Verify NFL player props using nfl_data_py"""
        logger.info(f"Verifying {len(props)} NFL prop bets...")
        settled = 0
        errors = 0

        try:
            import nfl_data_py as nfl
            import pandas as pd
        except ImportError:
            logger.error("nfl_data_py not installed. Run: pip install nfl_data_py")
            return {"settled": 0, "errors": len(props)}

        # Get week number from game date
        week = self._get_nfl_week_from_date(game_date)
        season = game_date.year

        # Fetch week's play-by-play data
        try:
            pbp_data = nfl.import_pbp_data([season])
            week_data = pbp_data[pbp_data["week"] == week]
        except Exception as e:
            logger.error(f"Error fetching NFL data: {e}")
            return {"settled": 0, "errors": len(props)}

        for prop in props:
            try:
                prop_details = self._parse_nfl_prop(prop.selection)
                if not prop_details:
                    logger.warning(f"Could not parse NFL prop: {prop.selection}")
                    errors += 1
                    continue

                # Get player stats from play-by-play data
                stats = self._extract_nfl_player_stats(
                    week_data, prop_details["player_name"], prop_details["stat_type"]
                )

                if stats is None:
                    logger.warning(
                        f"No NFL stats found for: {prop_details['player_name']}"
                    )
                    errors += 1
                    continue

                actual_value = stats.get(prop_details["stat_type"], 0)
                line_value = prop_details["line_value"]
                is_over = prop_details["is_over"]

                won = self._check_prop_outcome(actual_value, line_value, is_over)
                self._settle_prop_bet(prop, won, actual_value, line_value)
                settled += 1

                logger.info(
                    f"NFL prop settled: {prop.selection} - "
                    f"{'WON' if won else 'LOST'} (actual: {actual_value}, line: {line_value})"
                )

            except Exception as e:
                logger.error(f"Error verifying NFL prop {prop.id}: {e}")
                errors += 1

        return {"settled": settled, "errors": errors}

    def _parse_nfl_prop(self, selection: str) -> Optional[Dict]:
        """Parse NFL prop selection"""
        pattern = r"(.+?)\s+(over|under)\s+([\d.]+)\s+(.+)"
        match = re.match(pattern, selection, re.IGNORECASE)

        if not match:
            return None

        return {
            "player_name": match.group(1).strip(),
            "is_over": match.group(2).lower() == "over",
            "line_value": float(match.group(3)),
            "stat_type": match.group(4).strip().lower().replace(" ", "_"),
        }

    def _extract_nfl_player_stats(
        self, pbp_data, player_name: str, stat_type: str
    ) -> Optional[Dict]:
        """Extract NFL player stats from play-by-play data"""
        try:
            # Map stat types to relevant columns
            stat_mapping = {
                "passing_yards": "passing_yards",
                "rushing_yards": "rushing_yards",
                "receiving_yards": "receiving_yards",
                "passing_touchdowns": "pass_touchdown",
                "receptions": "complete_pass",
                "field_goals_made": "field_goal_result",
            }

            # Filter for plays involving the player
            player_filter = (
                (pbp_data["passer_player_name"] == player_name)
                | (pbp_data["rusher_player_name"] == player_name)
                | (pbp_data["receiver_player_name"] == player_name)
                | (pbp_data["kicker_player_name"] == player_name)
            )

            player_plays = pbp_data[player_filter]

            if player_plays.empty:
                return None

            # Calculate stat total
            column = stat_mapping.get(stat_type)
            if not column:
                return None

            if stat_type == "field_goals_made":
                total = (player_plays[column] == "made").sum()
            elif "touchdown" in stat_type:
                total = player_plays[column].sum()
            else:
                total = player_plays[column].sum()

            return {stat_type: total}

        except Exception as e:
            logger.error(f"Error extracting NFL stats: {e}")
            return None

    def _get_nfl_week_from_date(self, game_date) -> int:
        """Calculate NFL week number from date"""
        # NFL season starts first Thursday of September
        season_start = datetime(game_date.year, 9, 1)
        # Find first Thursday
        days_until_thursday = (3 - season_start.weekday()) % 7
        season_start += timedelta(days=days_until_thursday)

        days_since_start = (game_date - season_start.date()).days
        week = (days_since_start // 7) + 1
        return max(1, min(week, 18))

    # ==================== NHL VERIFICATION ====================

    async def _verify_nhl_props(self, props: List[Bet], game_date) -> Dict:
        """Verify NHL player props using NHL API"""
        logger.info(f"Verifying {len(props)} NHL prop bets...")
        settled = 0
        errors = 0

        # Fetch previous day's games
        games = self._fetch_nhl_games(game_date)

        for prop in props:
            try:
                prop_details = self._parse_nhl_prop(prop.selection)
                if not prop_details:
                    logger.warning(f"Could not parse NHL prop: {prop.selection}")
                    errors += 1
                    continue

                # Find player stats in games
                stats = self._find_nhl_player_stats(
                    games, prop_details["player_name"], prop_details["stat_type"]
                )

                if stats is None:
                    logger.warning(
                        f"No NHL stats found for: {prop_details['player_name']}"
                    )
                    errors += 1
                    continue

                actual_value = stats.get(prop_details["stat_type"], 0)
                line_value = prop_details["line_value"]
                is_over = prop_details["is_over"]

                won = self._check_prop_outcome(actual_value, line_value, is_over)
                self._settle_prop_bet(prop, won, actual_value, line_value)
                settled += 1

                logger.info(
                    f"NHL prop settled: {prop.selection} - "
                    f"{'WON' if won else 'LOST'} (actual: {actual_value}, line: {line_value})"
                )

            except Exception as e:
                logger.error(f"Error verifying NHL prop {prop.id}: {e}")
                errors += 1

        return {"settled": settled, "errors": errors}

    def _parse_nhl_prop(self, selection: str) -> Optional[Dict]:
        """Parse NHL prop selection"""
        pattern = r"(.+?)\s+(over|under)\s+([\d.]+)\s+(.+)"
        match = re.match(pattern, selection, re.IGNORECASE)

        if not match:
            return None

        stat_mapping = {
            "goals": "goals",
            "assists": "assists",
            "points": "points",
            "saves": "saves",
            "shots": "shots",
        }

        stat_type = match.group(4).strip().lower()
        stat_key = stat_mapping.get(stat_type, stat_type)

        return {
            "player_name": match.group(1).strip(),
            "is_over": match.group(2).lower() == "over",
            "line_value": float(match.group(3)),
            "stat_type": stat_key,
        }

    def _fetch_nhl_games(self, game_date) -> List[Dict]:
        """Fetch NHL games and stats from NHL API"""
        try:
            url = (
                f"https://api-web.nhle.com/v1/schedule/{game_date.strftime('%Y-%m-%d')}"
            )
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            schedule_data = response.json()
            games = []

            for date_data in schedule_data.get("gameWeek", []):
                for game in date_data.get("games", []):
                    game_id = game.get("id")
                    if game_id:
                        # Fetch detailed game stats
                        stats = self._fetch_nhl_game_stats(game_id)
                        if stats:
                            games.append(stats)

            return games

        except Exception as e:
            logger.error(f"Error fetching NHL games: {e}")
            return []

    def _fetch_nhl_game_stats(self, game_id: int) -> Optional[Dict]:
        """Fetch detailed stats for a specific NHL game"""
        try:
            url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching NHL game {game_id} stats: {e}")
            return None

    def _find_nhl_player_stats(
        self, games: List[Dict], player_name: str, stat_type: str
    ) -> Optional[Dict]:
        """Find player stats in NHL game data"""
        for game_data in games:
            if not game_data or "playerByGameStats" not in game_data:
                continue

            # Check both teams
            for team_key in ["awayTeam", "homeTeam"]:
                if team_key not in game_data["playerByGameStats"]:
                    continue

                team_stats = game_data["playerByGameStats"][team_key]

                # Check forwards
                for player in team_stats.get("forwards", []):
                    if (
                        player_name.lower()
                        in player.get("name", {}).get("default", "").lower()
                    ):
                        return {
                            "goals": player.get("goals", 0),
                            "assists": player.get("assists", 0),
                            "points": player.get("points", 0),
                            "shots": player.get("shots", 0),
                        }

                # Check defense
                for player in team_stats.get("defense", []):
                    if (
                        player_name.lower()
                        in player.get("name", {}).get("default", "").lower()
                    ):
                        return {
                            "goals": player.get("goals", 0),
                            "assists": player.get("assists", 0),
                            "points": player.get("points", 0),
                            "shots": player.get("shots", 0),
                        }

                # Check goalies
                for player in team_stats.get("goalies", []):
                    if (
                        player_name.lower()
                        in player.get("name", {}).get("default", "").lower()
                    ):
                        return {
                            "saves": player.get("saves", 0),
                            "goals": player.get("goalsAgainst", 0),
                        }

        return None

    # ==================== NBA VERIFICATION ====================

    async def _verify_nba_props(self, props: List[Bet], game_date) -> Dict:
        """Verify NBA player props using nba_api"""
        logger.info(f"Verifying {len(props)} NBA prop bets...")
        settled = 0
        errors = 0

        try:
            from nba_api.stats.endpoints import scoreboardv2, boxscoretraditionalv2
        except ImportError:
            logger.error("nba_api not installed. Run: pip install nba-api")
            return {"settled": 0, "errors": len(props)}

        # Get games from target date
        formatted_date = game_date.strftime("%m/%d/%Y")

        try:
            scoreboard = scoreboardv2.ScoreboardV2(game_date=formatted_date, timeout=60)
            games = scoreboard.game_header.get_dict()["data"]
        except Exception as e:
            logger.error(f"Error fetching NBA scoreboard: {e}")
            return {"settled": 0, "errors": len(props)}

        for prop in props:
            try:
                prop_details = self._parse_nba_prop(prop.selection)
                if not prop_details:
                    logger.warning(f"Could not parse NBA prop: {prop.selection}")
                    errors += 1
                    continue

                # Find player stats in games
                stats = self._find_nba_player_stats(
                    games, prop_details["player_name"], prop_details["stat_type"]
                )

                if stats is None:
                    logger.warning(
                        f"No NBA stats found for: {prop_details['player_name']}"
                    )
                    errors += 1
                    continue

                actual_value = stats.get(prop_details["stat_type"], 0)
                line_value = prop_details["line_value"]
                is_over = prop_details["is_over"]

                won = self._check_prop_outcome(actual_value, line_value, is_over)
                self._settle_prop_bet(prop, won, actual_value, line_value)
                settled += 1

                logger.info(
                    f"NBA prop settled: {prop.selection} - "
                    f"{'WON' if won else 'LOST'} (actual: {actual_value}, line: {line_value})"
                )

            except Exception as e:
                logger.error(f"Error verifying NBA prop {prop.id}: {e}")
                errors += 1

        return {"settled": settled, "errors": errors}

    def _parse_nba_prop(self, selection: str) -> Optional[Dict]:
        """Parse NBA prop selection"""
        pattern = r"(.+?)\s+(over|under)\s+([\d.]+)\s+(.+)"
        match = re.match(pattern, selection, re.IGNORECASE)

        if not match:
            return None

        stat_mapping = {
            "points": "PTS",
            "rebounds": "REB",
            "assists": "AST",
            "steals": "STL",
            "blocks": "BLK",
            "three pointers": "FG3M",
        }

        stat_type = match.group(4).strip().lower()
        stat_key = stat_mapping.get(stat_type, stat_type.upper())

        return {
            "player_name": match.group(1).strip(),
            "is_over": match.group(2).lower() == "over",
            "line_value": float(match.group(3)),
            "stat_type": stat_key,
            "stat_label": stat_type,
        }

    def _find_nba_player_stats(
        self, games: List, player_name: str, stat_type: str
    ) -> Optional[Dict]:
        """Find NBA player stats from games (named columns; PTS is not index 26)."""
        try:
            from nba_api.stats.endpoints import boxscoretraditionalv2

            for game in games:
                game_id = game[2]  # GAME_ID is at index 2

                try:
                    boxscore = boxscoretraditionalv2.BoxScoreTraditionalV2(
                        game_id=game_id, timeout=60
                    )
                    payload = boxscore.player_stats.get_dict()
                    headers = payload.get("headers") or []
                    for row in payload.get("data") or []:
                        record = dict(zip(headers, row))
                        box_name = record.get("PLAYER_NAME") or ""
                        if not _nba_player_names_match(player_name, box_name):
                            continue
                        stats = _nba_boxscore_row_to_stats(record)
                        if stats:
                            return stats

                except Exception as e:
                    logger.error(f"Error fetching NBA boxscore for game {game_id}: {e}")
                    continue

            return None

        except Exception as e:
            logger.error(f"Error finding NBA player stats: {e}")
            return None

    # ==================== COMMON UTILITIES ====================

    def verify_yetai_mlb_prop(
        self, bet: YetAIBet, game_date
    ) -> Optional[Tuple[str, str]]:
        """
        Settle a YetAI MLB prop using MLB Stats API.

        Returns (status, result_description) with status in won/lost/pushed, or
        None when stats are not available yet.
        """
        prop_details = self._parse_mlb_prop(bet.selection or "")
        if not prop_details:
            logger.warning(
                "Could not parse YetAI MLB prop selection: %r", bet.selection
            )
            return None

        stats = None
        for candidate_date in [game_date, game_date - timedelta(days=1)]:
            stats = self._fetch_mlb_player_stats(
                prop_details["player_name"],
                prop_details["stat_type"],
                candidate_date,
                is_pitching=prop_details.get("is_pitching", False),
            )
            if stats is not None:
                break
        if stats is None:
            return None

        actual_value = self._extract_stat_value(stats, prop_details["stat_type"])
        if actual_value is None:
            return None

        line_value = prop_details["line_value"]
        is_over = prop_details["is_over"]
        if actual_value == line_value:
            return (
                "pushed",
                f"Push: {prop_details['player_name']} exactly {line_value} "
                f"{prop_details['stat_type']}",
            )

        won = self._check_prop_outcome(actual_value, line_value, is_over)
        direction = "Over" if is_over else "Under"
        if won:
            return (
                "won",
                f"Won: {direction} {line_value} — actual {actual_value} "
                f"({prop_details['player_name']})",
            )
        return (
            "lost",
            f"Lost: {direction} {line_value} — actual {actual_value} "
            f"({prop_details['player_name']})",
        )

    def verify_yetai_nba_prop(
        self, bet: YetAIBet, game_date
    ) -> Optional[Tuple[str, str]]:
        """
        Settle a YetAI NBA prop using pred_*_actuals, then nba_api box scores.

        Returns (status, result_description) or None when stats are not available yet.
        """
        prop_details = self._parse_nba_prop(bet.selection or "")
        if not prop_details:
            logger.warning(
                "Could not parse YetAI NBA prop selection: %r", bet.selection
            )
            return None

        # Prefer live box score (named columns); DB actuals can be stale or mis-keyed.
        actual_value = self._fetch_nba_prop_actual_from_api(prop_details, game_date)
        if actual_value is None:
            actual_value = self._fetch_nba_prop_actual_from_db(
                prop_details["player_name"],
                prop_details.get("stat_label", ""),
                game_date,
            )
        if actual_value is None:
            return None

        line_value = prop_details["line_value"]
        is_over = prop_details["is_over"]
        if actual_value == line_value:
            return (
                "pushed",
                f"Push: {prop_details['player_name']} exactly {line_value} "
                f"{prop_details.get('stat_label', 'stat')}",
            )

        won = self._check_prop_outcome(actual_value, line_value, is_over)
        direction = "Over" if is_over else "Under"
        if won:
            return (
                "won",
                f"Won: {direction} {line_value} — actual {actual_value} "
                f"({prop_details['player_name']})",
            )
        return (
            "lost",
            f"Lost: {direction} {line_value} — actual {actual_value} "
            f"({prop_details['player_name']})",
        )

    def _fetch_nba_prop_actual_from_db(
        self, player_name: str, stat_label: str, game_date
    ) -> Optional[float]:
        from app.models.predictions_models import (
            AssistsActuals,
            PointsActuals,
            ReboundsActuals,
            StealsActuals,
        )

        table_map = {
            "points": (PointsActuals, "actual_points"),
            "rebounds": (ReboundsActuals, "actual_rebounds"),
            "assists": (AssistsActuals, "actual_assists"),
            "steals": (StealsActuals, "actual_steals"),
        }
        spec = table_map.get((stat_label or "").strip().lower())
        if not spec or not self.session:
            return None

        model, attr = spec
        rows = self.session.query(model).filter(model.date == game_date).all()
        for row in rows:
            name = getattr(row, "player_name", None) or ""
            if not name:
                continue
            if not _nba_player_names_match(player_name, name):
                continue
            value = getattr(row, attr, None)
            if value is not None:
                return float(value)
        return None

    def _fetch_nba_prop_actual_from_api(
        self, prop_details: Dict, game_date
    ) -> Optional[float]:
        try:
            from nba_api.stats.endpoints import scoreboardv2
        except ImportError:
            logger.warning("nba_api not installed; cannot verify NBA props via API")
            return None

        formatted_date = game_date.strftime("%m/%d/%Y")
        try:
            scoreboard = scoreboardv2.ScoreboardV2(game_date=formatted_date, timeout=60)
            games = scoreboard.game_header.get_dict()["data"]
        except Exception as e:
            logger.warning("NBA scoreboard fetch failed for %s: %s", game_date, e)
            return None

        stats = self._find_nba_player_stats(
            games,
            prop_details["player_name"],
            prop_details["stat_type"],
        )
        if stats is None:
            return None
        return float(stats.get(prop_details["stat_type"], 0))

    def _check_prop_outcome(
        self, actual_value: float, line_value: float, is_over: bool
    ) -> bool:
        """Check if prop bet won based on actual vs line value"""
        if is_over:
            return actual_value > line_value
        else:
            return actual_value < line_value

    def _settle_prop_bet(
        self, bet: Bet, won: bool, actual_value: float, line_value: float
    ) -> None:
        """Settle a prop bet and update database"""
        if won:
            bet.status = BetStatus.WON
            bet.result_amount = bet.amount + bet.potential_win
        else:
            bet.status = BetStatus.LOST
            bet.result_amount = 0

        bet.settled_at = datetime.utcnow()

        # Add settlement note to bet metadata
        if not hasattr(bet, "metadata") or bet.metadata is None:
            bet.metadata = {}

        bet.metadata["prop_settlement"] = {
            "actual_value": actual_value,
            "line_value": line_value,
            "settled_at": datetime.utcnow().isoformat(),
        }

        self.session.commit()

        # Send notification to user
        asyncio.create_task(self._send_notification(bet, won, actual_value, line_value))

    async def _send_notification(
        self, bet: Bet, won: bool, actual_value: float, line_value: float
    ) -> None:
        """Send websocket notification to user about settled prop"""
        try:
            await websocket_manager.send_personal_message(
                {
                    "type": "prop_settled",
                    "bet_id": str(bet.id),
                    "status": "won" if won else "lost",
                    "selection": bet.selection,
                    "actual_value": actual_value,
                    "line_value": line_value,
                    "result_amount": bet.result_amount,
                },
                bet.user_id,
            )
        except Exception as e:
            logger.error(f"Error sending prop settlement notification: {e}")
