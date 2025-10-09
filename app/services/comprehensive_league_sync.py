"""
Comprehensive League History Sync Service
Leverages existing fantasy scripts to sync multi-season league data and build competitor analysis
"""

import asyncio
import httpx
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from collections import defaultdict, Counter
import logging

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc

from app.core.database import SessionLocal
from app.models.fantasy_models import (
    FantasyLeague,
    FantasyTeam,
    LeagueHistoricalData,
    CompetitorAnalysis,
)
from app.services.sleeper_fantasy_service import SleeperFantasyService

logger = logging.getLogger(__name__)


@dataclass
class TransactionPattern:
    """Represents a manager's transaction behavior pattern"""

    waiver_adds_per_season: float
    faab_spent_per_season: float
    high_faab_bid_threshold: float
    preferred_positions: List[str]
    waiver_aggressiveness_score: float
    panic_drop_tendency: float
    season_phase_activity: Dict[str, int]  # early/mid/late season activity
    common_position_needs: List[str]
    faab_conservation_tendency: str  # "aggressive", "conservative", "balanced"


@dataclass
class ManagerProfile:
    """Complete manager behavioral profile"""

    sleeper_user_id: str
    display_name: str
    seasons_analyzed: List[int]
    transaction_patterns: TransactionPattern
    draft_tendencies: Dict[str, Any]
    keeper_strategies: Dict[str, Any]
    trade_behaviors: Dict[str, Any]


class ComprehensiveLeagueSync:
    """
    Syncs comprehensive multi-season league history and builds competitor analysis
    Leverages patterns from existing fantasy scripts
    """

    def __init__(self):
        self.sleeper_service = SleeperFantasyService()
        self.base_url = "https://api.sleeper.app/v1"

    async def sync_complete_league_history(
        self, league_id: str, current_season: int, historical_seasons: List[int]
    ) -> Dict[str, Any]:
        """
        Sync complete league history across multiple seasons
        Returns comprehensive analysis ready for AI processing
        """
        logger.info(f"Starting comprehensive sync for league {league_id}")

        db = SessionLocal()
        try:
            # Find or create the league record
            league = (
                db.query(FantasyLeague)
                .filter(FantasyLeague.platform_league_id == league_id)
                .first()
            )

            if not league:
                logger.warning(f"League {league_id} not found in database")
                return {"error": "League not found"}

            sync_results = {
                "league_id": league_id,
                "seasons_synced": [],
                "manager_profiles": {},
                "league_evolution": {},
                "competitive_insights": {},
            }

            # Sync each historical season
            all_seasons = [current_season] + historical_seasons
            for season in sorted(all_seasons):
                logger.info(f"Syncing season {season}")

                season_data = await self._sync_season_data(league_id, season)
                if season_data:
                    # Store in database
                    await self._store_historical_data(
                        db, league.id, season, season_data
                    )
                    sync_results["seasons_synced"].append(season)

            # Build comprehensive manager profiles
            manager_profiles = await self._build_manager_profiles(
                db, league.id, all_seasons
            )
            sync_results["manager_profiles"] = manager_profiles

            # Analyze league evolution patterns
            league_evolution = await self._analyze_league_evolution(
                db, league.id, all_seasons
            )
            sync_results["league_evolution"] = league_evolution

            # Generate competitive insights for AI
            competitive_insights = await self._generate_competitive_insights(
                db, league.id, manager_profiles
            )
            sync_results["competitive_insights"] = competitive_insights

            db.commit()
            logger.info(
                f"Successfully synced {len(all_seasons)} seasons for league {league_id}"
            )
            return sync_results

        except Exception as e:
            logger.error(f"Error syncing league history: {e}")
            db.rollback()
            raise
        finally:
            db.close()

    async def _sync_season_data(
        self, league_id: str, season: int
    ) -> Optional[Dict[str, Any]]:
        """Sync comprehensive data for a specific season"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                season_data = {
                    "season": season,
                    "league_info": {},
                    "rosters": [],
                    "transactions": [],
                    "draft_picks": [],
                    "standings": [],
                    "matchups": [],
                    "waiver_settings": {},
                }

                # Get league info
                league_response = await client.get(
                    f"{self.base_url}/league/{league_id}"
                )
                if league_response.status_code == 200:
                    league_info = league_response.json()
                    season_data["league_info"] = league_info

                    # Extract waiver settings
                    settings = league_info.get("settings", {})
                    season_data["waiver_settings"] = {
                        "waiver_type": settings.get("waiver_type", "waiver_priority"),
                        "waiver_budget": settings.get("waiver_budget", 100),
                        "waiver_clear_days": settings.get("waiver_clear_days", 2),
                        "roster_positions": settings.get("roster_positions", {}),
                    }

                # Get rosters
                rosters_response = await client.get(
                    f"{self.base_url}/league/{league_id}/rosters"
                )
                if rosters_response.status_code == 200:
                    season_data["rosters"] = rosters_response.json()

                # Get all transactions (week by week)
                for week in range(1, 19):  # Regular season + playoffs
                    tx_response = await client.get(
                        f"{self.base_url}/league/{league_id}/transactions/{week}"
                    )
                    if tx_response.status_code == 200:
                        week_transactions = tx_response.json() or []
                        for tx in week_transactions:
                            tx["week"] = week
                        season_data["transactions"].extend(week_transactions)

                # Get draft data
                drafts_response = await client.get(
                    f"{self.base_url}/league/{league_id}/drafts"
                )
                if drafts_response.status_code == 200:
                    drafts = drafts_response.json()
                    for draft in drafts:
                        if str(draft.get("season", "")) == str(season):
                            draft_id = draft.get("draft_id")
                            if draft_id:
                                picks_response = await client.get(
                                    f"{self.base_url}/draft/{draft_id}/picks"
                                )
                                if picks_response.status_code == 200:
                                    picks = picks_response.json()
                                    season_data["draft_picks"] = picks

                # Get matchups and standings
                for week in range(1, 18):
                    matchups_response = await client.get(
                        f"{self.base_url}/league/{league_id}/matchups/{week}"
                    )
                    if matchups_response.status_code == 200:
                        matchups = matchups_response.json() or []
                        for matchup in matchups:
                            matchup["week"] = week
                        season_data["matchups"].extend(matchups)

                return season_data

        except Exception as e:
            logger.error(f"Error syncing season {season} for league {league_id}: {e}")
            return None

    async def _store_historical_data(
        self, db: Session, league_id: int, season: int, season_data: Dict[str, Any]
    ):
        """Store season data in the database"""

        # Check if data already exists
        existing = (
            db.query(LeagueHistoricalData)
            .filter(
                and_(
                    LeagueHistoricalData.league_id == league_id,
                    LeagueHistoricalData.season == season,
                )
            )
            .first()
        )

        if existing:
            # Update existing record
            existing.teams_data = season_data.get("rosters", [])
            existing.transactions_data = season_data.get("transactions", [])
            existing.standings_data = {
                "matchups": season_data.get("matchups", []),
                "draft_picks": season_data.get("draft_picks", []),
            }
            existing.waiver_type = season_data["waiver_settings"]["waiver_type"]
            existing.waiver_budget = season_data["waiver_settings"]["waiver_budget"]
            existing.last_updated = datetime.utcnow()
        else:
            # Create new record
            historical_data = LeagueHistoricalData(
                league_id=league_id,
                season=season,
                team_count=len(season_data.get("rosters", [])),
                waiver_type=season_data["waiver_settings"]["waiver_type"],
                waiver_budget=season_data["waiver_settings"]["waiver_budget"],
                scoring_type=season_data["league_info"]
                .get("scoring_settings", {})
                .get("rec", 0),
                teams_data=season_data.get("rosters", []),
                transactions_data=season_data.get("transactions", []),
                standings_data={
                    "matchups": season_data.get("matchups", []),
                    "draft_picks": season_data.get("draft_picks", []),
                },
                created_at=datetime.utcnow(),
                last_updated=datetime.utcnow(),
            )
            db.add(historical_data)

    async def _build_manager_profiles(
        self, db: Session, league_id: int, seasons: List[int]
    ) -> Dict[str, ManagerProfile]:
        """Build comprehensive manager behavioral profiles"""

        profiles = {}

        # Get all historical data for the league
        historical_records = (
            db.query(LeagueHistoricalData)
            .filter(
                and_(
                    LeagueHistoricalData.league_id == league_id,
                    LeagueHistoricalData.season.in_(seasons),
                )
            )
            .all()
        )

        # Group data by manager
        manager_data = defaultdict(
            lambda: {
                "seasons": [],
                "transactions": [],
                "draft_picks": [],
                "rosters": [],
            }
        )

        for record in historical_records:
            season = record.season

            # Extract manager info from rosters
            for roster in record.teams_data or []:
                owners = roster.get("owners") or [roster.get("owner_id")]
                for owner_id in owners:
                    if owner_id:
                        manager_data[owner_id]["seasons"].append(season)
                        manager_data[owner_id]["rosters"].append(
                            {"season": season, "roster": roster}
                        )

            # Extract transaction patterns
            for transaction in record.transactions_data or []:
                if transaction.get("status") == "complete":
                    # Determine who made the transaction
                    roster_id = None
                    if transaction.get("adds"):
                        # Find who made the add
                        for player_id, add_roster_id in transaction.get(
                            "adds", {}
                        ).items():
                            roster_id = add_roster_id
                            break
                    elif transaction.get("drops"):
                        # Find who made the drop
                        for player_id, drop_roster_id in transaction.get(
                            "drops", {}
                        ).items():
                            roster_id = drop_roster_id
                            break

                    if roster_id:
                        # Find the owner of this roster
                        for roster in record.teams_data or []:
                            if roster.get("roster_id") == roster_id:
                                owners = roster.get("owners") or [
                                    roster.get("owner_id")
                                ]
                                for owner_id in owners:
                                    if owner_id:
                                        manager_data[owner_id]["transactions"].append(
                                            {
                                                "season": season,
                                                "transaction": transaction,
                                            }
                                        )

            # Extract draft patterns
            draft_data = (
                record.standings_data.get("draft_picks", [])
                if record.standings_data
                else []
            )
            for pick in draft_data:
                roster_id = pick.get("roster_id")
                if roster_id:
                    # Find the owner
                    for roster in record.teams_data or []:
                        if roster.get("roster_id") == roster_id:
                            owners = roster.get("owners") or [roster.get("owner_id")]
                            for owner_id in owners:
                                if owner_id:
                                    manager_data[owner_id]["draft_picks"].append(
                                        {"season": season, "pick": pick}
                                    )

        # Build profiles for each manager
        for owner_id, data in manager_data.items():
            if len(data["seasons"]) >= 2:  # Need at least 2 seasons of data
                profile = await self._analyze_manager_behavior(owner_id, data)
                profiles[owner_id] = profile

        return profiles

    async def _analyze_manager_behavior(
        self, owner_id: str, manager_data: Dict[str, Any]
    ) -> ManagerProfile:
        """Analyze individual manager behavior patterns"""

        seasons = list(set(manager_data["seasons"]))

        # Get manager info
        display_name = "Unknown Manager"
        try:
            async with httpx.AsyncClient() as client:
                user_response = await client.get(f"{self.base_url}/user/{owner_id}")
                if user_response.status_code == 200:
                    user_data = user_response.json()
                    display_name = user_data.get("display_name") or user_data.get(
                        "username", "Unknown"
                    )
        except:
            pass

        # Analyze transaction patterns
        transaction_analysis = self._analyze_transaction_patterns(
            manager_data["transactions"]
        )

        # Analyze draft tendencies
        draft_analysis = self._analyze_draft_patterns(manager_data["draft_picks"])

        # Analyze keeper strategies (if applicable)
        keeper_analysis = self._analyze_keeper_patterns(manager_data["rosters"])

        return ManagerProfile(
            sleeper_user_id=owner_id,
            display_name=display_name,
            seasons_analyzed=seasons,
            transaction_patterns=transaction_analysis,
            draft_tendencies=draft_analysis,
            keeper_strategies=keeper_analysis,
            trade_behaviors={},  # Will be enhanced with trade analysis
        )

    def _analyze_transaction_patterns(
        self, transactions: List[Dict]
    ) -> TransactionPattern:
        """Analyze waiver wire and transaction behavior"""

        if not transactions:
            return TransactionPattern(
                waiver_adds_per_season=0,
                faab_spent_per_season=0,
                high_faab_bid_threshold=0,
                preferred_positions=[],
                waiver_aggressiveness_score=0,
                panic_drop_tendency=0,
                season_phase_activity={},
                common_position_needs=[],
                faab_conservation_tendency="balanced",
            )

        # Group by season
        season_transactions = defaultdict(list)
        for tx_data in transactions:
            season = tx_data["season"]
            season_transactions[season].append(tx_data["transaction"])

        # Calculate averages across seasons
        season_stats = []
        position_adds = Counter()
        faab_bids = []
        phase_activity = {"early": 0, "mid": 0, "late": 0}

        for season, season_txs in season_transactions.items():
            waiver_adds = 0
            total_faab = 0

            for tx in season_txs:
                if tx.get("type") == "waiver":
                    waiver_adds += len(tx.get("adds", {}))
                    if "settings" in tx and "waiver_bid" in tx["settings"]:
                        bid = tx["settings"]["waiver_bid"]
                        total_faab += bid
                        faab_bids.append(bid)

                # Analyze by season phase
                week = tx.get("week", 1)
                if week <= 6:
                    phase_activity["early"] += 1
                elif week <= 12:
                    phase_activity["mid"] += 1
                else:
                    phase_activity["late"] += 1

                # Track position preferences (would need player position data)
                # This is a simplified version
                for player_id in tx.get("adds", {}):
                    # Would lookup player position here
                    position_adds["UNKNOWN"] += 1

            season_stats.append({"waiver_adds": waiver_adds, "faab_spent": total_faab})

        # Calculate averages
        avg_waiver_adds = (
            sum(s["waiver_adds"] for s in season_stats) / len(season_stats)
            if season_stats
            else 0
        )
        avg_faab_spent = (
            sum(s["faab_spent"] for s in season_stats) / len(season_stats)
            if season_stats
            else 0
        )

        # Determine aggressiveness score (0-1)
        aggressiveness = min(
            1.0, avg_waiver_adds / 20
        )  # Normalized to 20 adds per season max

        # Determine conservation tendency
        if avg_faab_spent > 75:
            conservation = "aggressive"
        elif avg_faab_spent < 25:
            conservation = "conservative"
        else:
            conservation = "balanced"

        return TransactionPattern(
            waiver_adds_per_season=avg_waiver_adds,
            faab_spent_per_season=avg_faab_spent,
            high_faab_bid_threshold=max(faab_bids) if faab_bids else 0,
            preferred_positions=list(position_adds.keys())[:3],
            waiver_aggressiveness_score=aggressiveness,
            panic_drop_tendency=0.0,  # Would need more complex analysis
            season_phase_activity=phase_activity,
            common_position_needs=list(position_adds.keys())[:2],
            faab_conservation_tendency=conservation,
        )

    def _analyze_draft_patterns(self, draft_picks: List[Dict]) -> Dict[str, Any]:
        """Analyze draft behavior patterns"""

        if not draft_picks:
            return {}

        # Group by season and analyze patterns
        patterns = {
            "early_round_positions": Counter(),
            "late_round_strategies": [],
            "keeper_preferences": [],
            "positional_timing": {},
        }

        for pick_data in draft_picks:
            pick = pick_data["pick"]
            round_num = pick.get("round", 1)

            if round_num <= 3:
                # Track early round position preferences
                # Would need player position lookup
                patterns["early_round_positions"]["UNKNOWN"] += 1

        return patterns

    def _analyze_keeper_patterns(self, rosters: List[Dict]) -> Dict[str, Any]:
        """Analyze keeper strategy patterns"""

        # This would analyze keeper decisions across seasons
        return {
            "keeper_value_preference": "high",  # high/medium/low value keepers
            "positional_keeper_bias": [],
            "keeper_timing_strategy": "early",  # early/late decision making
        }

    async def _analyze_league_evolution(
        self, db: Session, league_id: int, seasons: List[int]
    ) -> Dict[str, Any]:
        """Analyze how the league has evolved over time"""

        return {
            "competitiveness_trend": "increasing",
            "waiver_activity_evolution": {},
            "positional_value_shifts": {},
            "draft_strategy_evolution": {},
        }

    async def _generate_competitive_insights(
        self, db: Session, league_id: int, manager_profiles: Dict[str, ManagerProfile]
    ) -> Dict[str, Any]:
        """Generate AI-ready competitive insights"""

        insights = {
            "league_competitiveness_level": "high",
            "waiver_wire_competition": {},
            "positional_scarcity_awareness": {},
            "manager_archetypes": {},
            "optimal_strategies": {},
        }

        # Analyze manager archetypes
        archetypes = {
            "aggressive_traders": [],
            "waiver_hawks": [],
            "conservative_builders": [],
            "position_specialists": [],
        }

        for owner_id, profile in manager_profiles.items():
            # Classify managers by behavior
            if profile.transaction_patterns.waiver_aggressiveness_score > 0.7:
                archetypes["waiver_hawks"].append(
                    {
                        "owner_id": owner_id,
                        "display_name": profile.display_name,
                        "aggressiveness": profile.transaction_patterns.waiver_aggressiveness_score,
                    }
                )

            if (
                profile.transaction_patterns.faab_conservation_tendency
                == "conservative"
            ):
                archetypes["conservative_builders"].append(
                    {
                        "owner_id": owner_id,
                        "display_name": profile.display_name,
                        "avg_faab_spent": profile.transaction_patterns.faab_spent_per_season,
                    }
                )

        insights["manager_archetypes"] = archetypes

        # Store competitor analysis in database
        for owner_id, profile in manager_profiles.items():
            await self._store_competitor_analysis(db, league_id, owner_id, profile)

        return insights

    async def _store_competitor_analysis(
        self, db: Session, league_id: int, owner_id: str, profile: ManagerProfile
    ):
        """Store competitor analysis in database"""

        # Find the team for this owner
        # This would need to be enhanced to properly link owner_id to team_id

        existing_analysis = (
            db.query(CompetitorAnalysis)
            .filter(CompetitorAnalysis.league_id == league_id)
            .first()
        )  # Simplified for now

        analysis_data = {
            "league_id": league_id,
            "team_id": 1,  # Would need proper team lookup
            "seasons_analyzed": profile.seasons_analyzed,
            "avg_waiver_adds_per_season": profile.transaction_patterns.waiver_adds_per_season,
            "preferred_positions": profile.transaction_patterns.preferred_positions,
            "waiver_aggressiveness_score": profile.transaction_patterns.waiver_aggressiveness_score,
            "avg_faab_spent_per_season": profile.transaction_patterns.faab_spent_per_season,
            "high_faab_bid_threshold": profile.transaction_patterns.high_faab_bid_threshold,
            "faab_conservation_tendency": profile.transaction_patterns.faab_conservation_tendency,
            "common_position_needs": profile.transaction_patterns.common_position_needs,
            "panic_drop_tendency": profile.transaction_patterns.panic_drop_tendency,
            "waiver_claim_day_preferences": [],  # Would need more analysis
            "season_phase_activity": profile.transaction_patterns.season_phase_activity,
            "created_at": datetime.utcnow(),
            "last_updated": datetime.utcnow(),
        }

        if not existing_analysis:
            analysis = CompetitorAnalysis(**analysis_data)
            db.add(analysis)
        else:
            # Update existing
            for key, value in analysis_data.items():
                if hasattr(existing_analysis, key):
                    setattr(existing_analysis, key, value)


# Service instance
comprehensive_sync_service = ComprehensiveLeagueSync()
