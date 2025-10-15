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
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.core.database import SessionLocal
from app.models.database_models import Bet, BetStatus, BetType
from app.services.websocket_manager import manager as websocket_manager

logger = logging.getLogger(__name__)


class PlayerPropVerificationService:
    """Service for verifying player prop bets using sport-specific stats APIs"""

    def __init__(self):
        self.session: Optional[Session] = None

    async def verify_previous_day_props(self) -> Dict:
        """
        Main entry point - verify all pending prop bets from previous day

        Returns:
            Dict with verification results
        """
        logger.info("🏈 Starting player prop verification for previous day...")

        self.session = SessionLocal()
        try:
            # Get all pending prop bets from yesterday
            yesterday = datetime.utcnow().date() - timedelta(days=1)
            pending_props = self._get_pending_props(yesterday)

            if not pending_props:
                logger.info("No pending prop bets from yesterday to verify")
                return {"verified": 0, "settled": 0, "errors": 0}

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

            results["verified"] = len(pending_props)

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
                    prop_details["player_name"], prop_details["stat_type"], game_date
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

        # Map stat types to MLB API fields
        stat_mapping = {
            "pitcher outs": "outs",
            "strikeouts": "strikeouts",
            "hits allowed": "hits",
            "earned runs": "earnedRuns",
            "total bases": "totalBases",
            "runs": "runs",
            "rbis": "rbi",
            "home runs": "homeRuns",
        }

        stat_key = stat_mapping.get(stat_type.lower(), stat_type.lower())

        return {
            "player_name": player_name,
            "stat_type": stat_key,
            "line_value": line_value,
            "is_over": over_under == "over",
        }

    def _fetch_mlb_player_stats(
        self, player_name: str, stat_type: str, game_date
    ) -> Optional[Dict]:
        """Fetch MLB player stats from MLB Stats API"""
        try:
            # First, search for player ID
            search_url = (
                f"https://statsapi.mlb.com/api/v1/people/search?names={player_name}"
            )
            response = requests.get(search_url, timeout=10)
            response.raise_for_status()

            search_data = response.json()
            if not search_data.get("people"):
                return None

            player_id = search_data["people"][0]["id"]

            # Fetch game logs for pitcher
            if stat_type in ["outs", "strikeouts", "hits", "earnedRuns"]:
                url = f"https://statsapi.mlb.com/api/v1/people/{player_id}?hydrate=stats(group=[pitching],type=[gameLog],season=2025)"
            else:
                url = f"https://statsapi.mlb.com/api/v1/people/{player_id}?hydrate=stats(group=[hitting],type=[gameLog],season=2025)"

            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            if "people" not in data or not data["people"]:
                return None

            stats = data["people"][0].get("stats", [])
            game_logs = next(
                (
                    stat["splits"]
                    for stat in stats
                    if stat["type"]["displayName"] == "gameLog"
                ),
                [],
            )

            # Find the game from target date
            for game in game_logs:
                game_date_str = game.get("date")
                if game_date_str and game_date_str.startswith(
                    game_date.strftime("%Y-%m-%d")
                ):
                    return game.get("stat", {})

            return None

        except Exception as e:
            logger.error(f"Error fetching MLB stats for {player_name}: {e}")
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
        }

    def _find_nba_player_stats(
        self, games: List, player_name: str, stat_type: str
    ) -> Optional[Dict]:
        """Find NBA player stats from games"""
        try:
            from nba_api.stats.endpoints import boxscoretraditionalv2

            for game in games:
                game_id = game[2]  # GAME_ID is at index 2

                try:
                    boxscore = boxscoretraditionalv2.BoxScoreTraditionalV2(
                        game_id=game_id, timeout=60
                    )
                    player_stats = boxscore.player_stats.get_dict()["data"]

                    for player in player_stats:
                        player_full_name = player[5]  # PLAYER_NAME is at index 5
                        if player_name.lower() in player_full_name.lower():
                            # Return stats dict with relevant fields
                            return {
                                "PTS": player[26],  # Points
                                "REB": player[20],  # Rebounds
                                "AST": player[21],  # Assists
                                "STL": player[22],  # Steals
                                "BLK": player[23],  # Blocks
                                "FG3M": player[12],  # 3-pointers made
                            }

                except Exception as e:
                    logger.error(f"Error fetching NBA boxscore for game {game_id}: {e}")
                    continue

            return None

        except Exception as e:
            logger.error(f"Error finding NBA player stats: {e}")
            return None

    # ==================== COMMON UTILITIES ====================

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
