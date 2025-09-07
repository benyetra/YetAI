"""
SQLAlchemy models for Fantasy Sports integration
"""
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, JSON, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
from app.models.database_models import User
import enum
from datetime import datetime

class FantasyPlatform(str, enum.Enum):
    SLEEPER = "sleeper"
    YAHOO = "yahoo"
    ESPN = "espn"

class FantasyLeagueType(str, enum.Enum):
    REDRAFT = "redraft"
    KEEPER = "keeper"
    DYNASTY = "dynasty"

class FantasyPosition(str, enum.Enum):
    QB = "QB"
    RB = "RB" 
    WR = "WR"
    TE = "TE"
    K = "K"
    DEF = "DEF"
    FLEX = "FLEX"
    SUPER_FLEX = "SUPER_FLEX"
    BENCH = "BENCH"
    IR = "IR"

class PlayerStatus(str, enum.Enum):
    ACTIVE = "active"
    INJURED = "injured"
    OUT = "out"
    DOUBTFUL = "doubtful"
    QUESTIONABLE = "questionable"
    PROBABLE = "probable"
    BYE = "bye"

class TransactionType(str, enum.Enum):
    ADD = "add"
    DROP = "drop"
    TRADE = "trade"
    WAIVER = "waiver"

class RecommendationType(str, enum.Enum):
    START_SIT = "start_sit"
    WAIVER_WIRE = "waiver_wire"
    TRADE = "trade"

class FantasyUser(Base):
    """Links platform user accounts to YetAI users"""
    __tablename__ = "fantasy_users"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    platform = Column(Enum(FantasyPlatform), nullable=False)
    platform_user_id = Column(String(255), nullable=False)
    platform_username = Column(String(255))
    
    # Platform-specific auth data
    access_token = Column(Text)  # For OAuth platforms
    refresh_token = Column(Text)
    token_expires_at = Column(DateTime)
    
    # Connection status
    is_active = Column(Boolean, default=True)
    last_sync = Column(DateTime)
    sync_error = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User")
    leagues = relationship("FantasyLeague", back_populates="fantasy_user")

class FantasyLeague(Base):
    """Fantasy league information"""
    __tablename__ = "fantasy_leagues"
    
    id = Column(Integer, primary_key=True, index=True)
    fantasy_user_id = Column(Integer, ForeignKey("fantasy_users.id"), nullable=False)
    platform = Column(Enum(FantasyPlatform), nullable=False)
    platform_league_id = Column(String(255), nullable=False)
    
    # League details
    name = Column(String(255), nullable=False)
    league_type = Column(Enum(FantasyLeagueType), default=FantasyLeagueType.REDRAFT)
    sport = Column(String(50), default="nfl")
    season = Column(Integer, nullable=False)
    
    # League settings
    team_count = Column(Integer)
    scoring_type = Column(String(50))  # standard, ppr, half_ppr, etc.
    roster_size = Column(Integer)
    playoff_teams = Column(Integer)
    trade_deadline = Column(DateTime)
    
    # Waiver settings
    waiver_type = Column(String(50))  # "FAAB", "waiver_priority", "free_agent"
    waiver_budget = Column(Integer)  # FAAB budget for the season
    waiver_clear_days = Column(Integer)  # Days on waivers
    
    # League configuration
    roster_positions = Column(JSON)  # Position slots configuration
    
    # Sync settings
    is_synced = Column(Boolean, default=True)
    sync_enabled = Column(Boolean, default=True)
    last_sync = Column(DateTime)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    fantasy_user = relationship("FantasyUser", back_populates="leagues")
    teams = relationship("FantasyTeam", back_populates="league")
    matchups = relationship("FantasyMatchup", back_populates="league")

class FantasyTeam(Base):
    """Fantasy team within a league"""
    __tablename__ = "fantasy_teams"
    
    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("fantasy_leagues.id"), nullable=False)
    platform_team_id = Column(String(255), nullable=False)
    
    # Team details
    name = Column(String(255), nullable=False)
    owner_name = Column(String(255))
    is_user_team = Column(Boolean, default=False)  # True if this is the connected user's team
    
    # Team stats
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    ties = Column(Integer, default=0)
    points_for = Column(Float, default=0)
    points_against = Column(Float, default=0)
    
    # Waiver and standings
    waiver_position = Column(Integer)
    playoff_seed = Column(Integer)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    league = relationship("FantasyLeague", back_populates="teams")
    roster_spots = relationship("FantasyRosterSpot", back_populates="team")

class FantasyPlayer(Base):
    """Fantasy player information"""
    __tablename__ = "fantasy_players"
    
    id = Column(Integer, primary_key=True, index=True)
    platform = Column(Enum(FantasyPlatform), nullable=False)
    platform_player_id = Column(String(255), nullable=False)
    
    # Player details
    name = Column(String(255), nullable=False)
    position = Column(Enum(FantasyPosition), nullable=False)
    team = Column(String(10))  # NFL team abbreviation
    jersey_number = Column(String(5))
    
    # Player metadata
    age = Column(Integer)
    height = Column(String(10))
    weight = Column(Integer)
    college = Column(String(255))
    experience = Column(Integer)  # Years in league
    
    # Status
    status = Column(Enum(PlayerStatus), default=PlayerStatus.ACTIVE)
    injury_description = Column(String(500))
    
    # Fantasy metrics (updated regularly)
    adp = Column(Float)  # Average draft position
    ownership_percentage = Column(Float)
    add_percentage = Column(Float)  # Weekly add percentage
    drop_percentage = Column(Float)  # Weekly drop percentage
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    roster_spots = relationship("FantasyRosterSpot", back_populates="player")
    projections = relationship("PlayerProjection", back_populates="player")

class FantasyRosterSpot(Base):
    """Player roster spots on fantasy teams"""
    __tablename__ = "fantasy_roster_spots"
    
    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("fantasy_players.id"), nullable=False)
    
    position = Column(Enum(FantasyPosition), nullable=False)
    week = Column(Integer)  # NFL week, null for season-long
    is_starter = Column(Boolean, default=False)
    
    # Performance tracking
    points_scored = Column(Float, default=0)
    projected_points = Column(Float, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    team = relationship("FantasyTeam", back_populates="roster_spots")
    player = relationship("FantasyPlayer", back_populates="roster_spots")

class FantasyMatchup(Base):
    """Weekly fantasy matchups"""
    __tablename__ = "fantasy_matchups"
    
    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("fantasy_leagues.id"), nullable=False)
    
    week = Column(Integer, nullable=False)
    matchup_id = Column(String(255))  # Platform-specific matchup ID
    
    team1_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    team2_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    
    team1_score = Column(Float, default=0)
    team2_score = Column(Float, default=0)
    
    is_complete = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    league = relationship("FantasyLeague", back_populates="matchups")
    team1 = relationship("FantasyTeam", foreign_keys=[team1_id])
    team2 = relationship("FantasyTeam", foreign_keys=[team2_id])

class PlayerProjection(Base):
    """AI-generated player projections"""
    __tablename__ = "player_projections"
    
    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("fantasy_players.id"), nullable=False)
    
    week = Column(Integer, nullable=False)
    season = Column(Integer, nullable=False)
    
    # Projections
    projected_points = Column(Float, nullable=False)
    floor = Column(Float)  # Conservative projection
    ceiling = Column(Float)  # Optimistic projection
    
    # Matchup analysis
    opponent = Column(String(10))  # Opposing team
    vegas_implied_total = Column(Float)  # Team's implied total from betting lines
    game_script_score = Column(Float)  # Positive/negative game script
    
    # Advanced metrics
    target_share = Column(Float)  # For skill position players
    red_zone_looks = Column(Float)
    snap_percentage = Column(Float)
    
    # AI confidence and reasoning
    confidence = Column(Float, nullable=False)  # 0-100 confidence score
    reasoning = Column(Text)  # AI explanation
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    player = relationship("FantasyPlayer", back_populates="projections")

class FantasyRecommendation(Base):
    """YetAI fantasy recommendations"""
    __tablename__ = "fantasy_recommendations"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    league_id = Column(Integer, ForeignKey("fantasy_leagues.id"), nullable=False)
    
    recommendation_type = Column(Enum(RecommendationType), nullable=False)
    week = Column(Integer, nullable=False)
    
    # Recommendation details
    title = Column(String(255), nullable=False)
    description = Column(Text)
    priority = Column(Integer, default=5)  # 1-10 priority scale
    
    # Player references
    primary_player_id = Column(Integer, ForeignKey("fantasy_players.id"))
    secondary_player_id = Column(Integer, ForeignKey("fantasy_players.id"))  # For trades
    
    # AI analysis
    confidence = Column(Float, nullable=False)
    reasoning = Column(Text)
    expected_impact = Column(Float)  # Projected point impact
    
    # Status
    is_active = Column(Boolean, default=True)
    user_dismissed = Column(Boolean, default=False)
    user_acted = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    
    # Relationships
    user = relationship("User")
    league = relationship("FantasyLeague")
    primary_player = relationship("FantasyPlayer", foreign_keys=[primary_player_id])
    secondary_player = relationship("FantasyPlayer", foreign_keys=[secondary_player_id])

class FantasyTransaction(Base):
    """Track fantasy transactions for analysis"""
    __tablename__ = "fantasy_transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("fantasy_leagues.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    
    transaction_type = Column(Enum(TransactionType), nullable=False)
    week = Column(Integer)
    
    # Players involved
    added_player_id = Column(Integer, ForeignKey("fantasy_players.id"))
    dropped_player_id = Column(Integer, ForeignKey("fantasy_players.id"))
    
    # Transaction details
    waiver_priority = Column(Integer)
    fab_bid = Column(Integer)  # FAAB bid amount
    trade_details = Column(JSON)  # For complex trade data
    
    processed_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    league = relationship("FantasyLeague")
    team = relationship("FantasyTeam")
    added_player = relationship("FantasyPlayer", foreign_keys=[added_player_id])
    dropped_player = relationship("FantasyPlayer", foreign_keys=[dropped_player_id])

class WaiverWireTarget(Base):
    """AI-identified waiver wire targets"""
    __tablename__ = "waiver_wire_targets"
    
    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("fantasy_leagues.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("fantasy_players.id"), nullable=False)
    
    week = Column(Integer, nullable=False)
    
    # Opportunity metrics
    opportunity_score = Column(Float, nullable=False)  # 0-100 opportunity rating
    ownership_percentage = Column(Float)  # League ownership %
    trending_direction = Column(String(20))  # up, down, stable
    
    # Situation analysis
    situation_description = Column(Text)
    target_reason = Column(Text)  # Why this player is a target
    suggested_fab_percentage = Column(Float)  # FAAB % to bid
    
    # Projections
    rest_of_season_value = Column(Float)
    immediate_value = Column(Float)  # Next 2-3 weeks
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    league = relationship("FantasyLeague")
    player = relationship("FantasyPlayer")

class LeagueHistoricalData(Base):
    """Historical league data for competitor analysis"""
    __tablename__ = "league_historical_data"
    
    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("fantasy_leagues.id"), nullable=False)
    season = Column(Integer, nullable=False)
    
    # League metadata for historical season
    team_count = Column(Integer)
    waiver_type = Column(String(50))
    waiver_budget = Column(Integer)
    scoring_type = Column(String(50))
    
    # Raw data storage
    teams_data = Column(JSON)  # Team rosters, records, etc.
    transactions_data = Column(JSON)  # All transactions for season
    standings_data = Column(JSON)  # Final standings
    
    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    league = relationship("FantasyLeague")

class CompetitorAnalysis(Base):
    """Analysis of competitor tendencies in leagues"""
    __tablename__ = "competitor_analysis"
    
    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("fantasy_leagues.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    
    # Analysis period
    seasons_analyzed = Column(JSON)  # List of seasons included in analysis
    
    # Waiver wire tendencies
    avg_waiver_adds_per_season = Column(Float, default=0)
    preferred_positions = Column(JSON)  # Position preferences in adds
    waiver_aggressiveness_score = Column(Float)  # 0-100 aggressiveness rating
    
    # FAAB tendencies (if applicable)
    avg_faab_spent_per_season = Column(Float)
    high_faab_bid_threshold = Column(Float)  # Amount considered "high" for this manager
    faab_conservation_tendency = Column(String(20))  # conservative, moderate, aggressive
    
    # Position needs patterns
    common_position_needs = Column(JSON)  # Historical position needs by week
    panic_drop_tendency = Column(Float)  # Likelihood to make reactionary drops
    
    # Timing patterns
    waiver_claim_day_preferences = Column(JSON)  # When they typically make claims
    season_phase_activity = Column(JSON)  # Activity by early/mid/late season
    
    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    league = relationship("FantasyLeague")
    team = relationship("FantasyTeam")

class PlayerAnalytics(Base):
    """Advanced player usage and performance analytics"""
    __tablename__ = "player_analytics"
    
    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("fantasy_players.id"), nullable=False)
    
    # Time period
    week = Column(Integer, nullable=False)
    season = Column(Integer, nullable=False)
    game_date = Column(DateTime)
    opponent = Column(String(10))  # Opposing team abbreviation
    
    # Snap Count Analytics
    total_snaps = Column(Integer)
    offensive_snaps = Column(Integer)
    special_teams_snaps = Column(Integer)
    snap_percentage = Column(Float)  # % of team's offensive snaps
    snap_share_rank = Column(Integer)  # Rank among position players
    
    # Target Share Analytics (WR/TE/RB)
    targets = Column(Integer, default=0)
    team_total_targets = Column(Integer)
    target_share = Column(Float)  # % of team targets
    air_yards = Column(Integer)  # Total air yards from targets
    air_yards_share = Column(Float)  # % of team air yards
    average_depth_of_target = Column(Float)  # aDOT
    target_separation = Column(Float)  # Average yards of separation on targets
    
    # Red Zone Usage
    red_zone_snaps = Column(Integer, default=0)
    red_zone_targets = Column(Integer, default=0)
    red_zone_carries = Column(Integer, default=0)
    red_zone_touches = Column(Integer, default=0)  # Targets + carries
    red_zone_share = Column(Float)  # % of team's red zone opportunities
    red_zone_efficiency = Column(Float)  # Scoring rate in red zone
    
    # Route Running (WR/TE)
    routes_run = Column(Integer, default=0)
    route_participation = Column(Float)  # % of passing plays where player ran route
    slot_rate = Column(Float)  # % of snaps in slot vs outside
    deep_target_rate = Column(Float)  # % of targets 20+ yards downfield
    
    # Rushing Usage (RB/QB)
    carries = Column(Integer, default=0)
    rushing_yards = Column(Integer, default=0)
    goal_line_carries = Column(Integer, default=0)
    carry_share = Column(Float)  # % of team carries
    yards_before_contact = Column(Float)
    yards_after_contact = Column(Float)
    broken_tackles = Column(Integer, default=0)
    
    # Receiving Production
    receptions = Column(Integer, default=0)
    receiving_yards = Column(Integer, default=0)
    yards_after_catch = Column(Integer, default=0)
    yards_after_catch_per_reception = Column(Float)
    contested_catch_rate = Column(Float)  # Success rate on contested targets
    drop_rate = Column(Float)
    
    # Game Context
    team_pass_attempts = Column(Integer)
    team_rush_attempts = Column(Integer)
    team_red_zone_attempts = Column(Integer)
    game_script = Column(Float)  # Positive = favorable, negative = unfavorable
    time_of_possession = Column(Float)  # Team's TOP in minutes
    
    # Advanced Efficiency Metrics
    ppr_points = Column(Float)
    half_ppr_points = Column(Float)
    standard_points = Column(Float)
    points_per_snap = Column(Float)
    points_per_target = Column(Float)
    points_per_touch = Column(Float)  # Targets + carries
    
    # Consistency Metrics
    boom_rate = Column(Float)  # % of games with 20+ fantasy points
    bust_rate = Column(Float)  # % of games with <5 fantasy points
    weekly_variance = Column(Float)  # Standard deviation of weekly scores
    floor_score = Column(Float)  # 25th percentile fantasy score
    ceiling_score = Column(Float)  # 75th percentile fantasy score
    
    # Injury/Availability
    injury_designation = Column(String(20))  # Healthy, Questionable, Doubtful, Out
    snaps_missed_injury = Column(Integer, default=0)
    games_missed_season = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    player = relationship("FantasyPlayer")

class PlayerTrends(Base):
    """Track player performance trends over time"""
    __tablename__ = "player_trends"
    
    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("fantasy_players.id"), nullable=False)
    
    # Trend period
    season = Column(Integer, nullable=False)
    trend_type = Column(String(50), nullable=False)  # 'weekly', 'monthly', 'season'
    period_start = Column(Integer)  # Week or month start
    period_end = Column(Integer)    # Week or month end
    
    # Usage Trends
    snap_share_trend = Column(Float)  # +/- change in snap share
    target_share_trend = Column(Float)  # +/- change in target share
    red_zone_usage_trend = Column(Float)  # +/- change in RZ usage
    carry_share_trend = Column(Float)  # +/- change in carry share
    
    # Performance Trends
    fantasy_points_trend = Column(Float)  # Points per game trend
    efficiency_trend = Column(Float)  # Points per opportunity trend
    consistency_trend = Column(Float)  # Variance trend (lower = more consistent)
    
    # Context Changes
    role_change_indicator = Column(Boolean, default=False)  # Significant role change
    role_change_description = Column(String(500))  # What changed
    opportunity_change_score = Column(Float)  # Overall opportunity change score
    
    # Predictive Metrics
    momentum_score = Column(Float)  # Overall momentum (positive/negative)
    sustainability_score = Column(Float)  # How sustainable current performance is
    buy_low_indicator = Column(Boolean, default=False)  # Player may be undervalued
    sell_high_indicator = Column(Boolean, default=False)  # Player may be overvalued
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    player = relationship("FantasyPlayer")

class TradeStatus(str, enum.Enum):
    PROPOSED = "proposed"
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    CANCELLED = "cancelled"

class TradeGrade(str, enum.Enum):
    A_PLUS = "A+"
    A = "A"
    A_MINUS = "A-"
    B_PLUS = "B+"
    B = "B"
    B_MINUS = "B-"
    C_PLUS = "C+"
    C = "C"
    C_MINUS = "C-"
    D = "D"
    F = "F"

class DraftPick(Base):
    """Draft picks that can be traded"""
    __tablename__ = "draft_picks"
    
    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("fantasy_leagues.id"), nullable=False)
    current_owner_team_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    original_owner_team_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    
    # Pick details
    season = Column(Integer, nullable=False)
    round_number = Column(Integer, nullable=False)  # 1st, 2nd, 3rd round, etc.
    pick_number = Column(Integer)  # Overall pick number if known
    
    # Pick metadata
    is_tradeable = Column(Boolean, default=True)
    trade_deadline = Column(DateTime)  # When this pick can no longer be traded
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    league = relationship("FantasyLeague")
    current_owner = relationship("FantasyTeam", foreign_keys=[current_owner_team_id])
    original_owner = relationship("FantasyTeam", foreign_keys=[original_owner_team_id])

class Trade(Base):
    """Trade proposals and completed trades"""
    __tablename__ = "trades"
    
    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("fantasy_leagues.id"), nullable=False)
    
    # Trade participants
    team1_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    team2_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    
    # Trade metadata
    status = Column(Enum(TradeStatus), default=TradeStatus.PROPOSED)
    proposed_by_team_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    
    # Trade details (stored as JSON for flexibility)
    team1_gives = Column(JSON)  # {"players": [player_ids], "picks": [pick_ids], "faab": amount}
    team2_gives = Column(JSON)  # {"players": [player_ids], "picks": [pick_ids], "faab": amount}
    
    # Trade timing
    proposed_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)  # When trade proposal expires
    processed_at = Column(DateTime)  # When trade was accepted/declined
    
    # Trade context
    trade_reason = Column(Text)  # Why this trade was proposed
    is_ai_suggested = Column(Boolean, default=False)  # Generated by AI recommendation
    
    # Veto system
    veto_deadline = Column(DateTime)  # League veto deadline if applicable
    veto_count = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    league = relationship("FantasyLeague")
    team1 = relationship("FantasyTeam", foreign_keys=[team1_id])
    team2 = relationship("FantasyTeam", foreign_keys=[team2_id])
    proposed_by = relationship("FantasyTeam", foreign_keys=[proposed_by_team_id])
    evaluations = relationship("TradeEvaluation", back_populates="trade")
    recommendations = relationship("TradeRecommendation", back_populates="trade")

class TradeEvaluation(Base):
    """AI-generated trade analysis and grading"""
    __tablename__ = "trade_evaluations"
    
    id = Column(Integer, primary_key=True, index=True)
    trade_id = Column(Integer, ForeignKey("trades.id"), nullable=False)
    
    # Overall trade grades
    team1_grade = Column(Enum(TradeGrade), nullable=False)
    team2_grade = Column(Enum(TradeGrade), nullable=False)
    
    # Detailed analysis
    team1_analysis = Column(JSON)  # Detailed breakdown for team 1
    team2_analysis = Column(JSON)  # Detailed breakdown for team 2
    
    # Value analysis
    team1_value_given = Column(Float)  # Total value given up
    team1_value_received = Column(Float)  # Total value received
    team2_value_given = Column(Float)  # Total value given up
    team2_value_received = Column(Float)  # Total value received
    
    # Context analysis
    trade_context = Column(JSON)  # League context, timing, needs analysis
    fairness_score = Column(Float)  # 0-100 how fair the trade is
    
    # AI reasoning
    ai_summary = Column(Text)  # Overall trade summary
    key_factors = Column(JSON)  # Key factors that influenced the evaluation
    
    # Evaluation metadata
    evaluation_version = Column(String(10), default="1.0")  # Algorithm version
    confidence = Column(Float)  # 0-100 confidence in evaluation
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    trade = relationship("Trade", back_populates="evaluations")

class TradeRecommendation(Base):
    """AI-generated trade recommendations"""
    __tablename__ = "trade_recommendations"
    
    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("fantasy_leagues.id"), nullable=False)
    requesting_team_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    target_team_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    trade_id = Column(Integer, ForeignKey("trades.id"))  # If trade was actually proposed
    
    # Recommendation details
    recommendation_type = Column(String(50))  # "position_need", "buy_low", "sell_high", etc.
    priority_score = Column(Float)  # 0-100 priority of this recommendation
    
    # Trade structure
    suggested_trade = Column(JSON)  # Complete trade proposal
    
    # Analysis
    mutual_benefit_score = Column(Float)  # How much both teams benefit
    likelihood_accepted = Column(Float)  # 0-100 chance of acceptance
    
    # Reasoning
    recommendation_reason = Column(Text)  # Why this trade makes sense
    timing_factor = Column(Text)  # Why now is a good time
    
    # Status
    is_active = Column(Boolean, default=True)
    was_proposed = Column(Boolean, default=False)
    user_dismissed = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)  # When recommendation becomes stale
    
    # Relationships
    league = relationship("FantasyLeague")
    requesting_team = relationship("FantasyTeam", foreign_keys=[requesting_team_id])
    target_team = relationship("FantasyTeam", foreign_keys=[target_team_id])
    trade = relationship("Trade", back_populates="recommendations")

class PlayerValue(Base):
    """Dynamic player values for trade analysis"""
    __tablename__ = "player_values"
    
    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("fantasy_players.id"), nullable=False)
    league_id = Column(Integer, ForeignKey("fantasy_leagues.id"), nullable=False)
    
    # Time period
    week = Column(Integer, nullable=False)
    season = Column(Integer, nullable=False)
    
    # Base values
    rest_of_season_value = Column(Float)  # ROS value 0-100
    dynasty_value = Column(Float)  # Long-term dynasty value
    redraft_value = Column(Float)  # Single season value
    
    # Context-specific values
    ppr_value = Column(Float)  # PPR league value
    standard_value = Column(Float)  # Standard league value
    superflex_value = Column(Float)  # Superflex league value
    
    # Market indicators
    trade_frequency = Column(Float)  # How often player is traded
    buy_low_indicator = Column(Boolean, default=False)
    sell_high_indicator = Column(Boolean, default=False)
    
    # Volatility and risk
    value_volatility = Column(Float)  # How much value fluctuates
    injury_risk_factor = Column(Float)  # 0-1 injury risk
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    player = relationship("FantasyPlayer")
    league = relationship("FantasyLeague")

class TeamNeedsAnalysis(Base):
    """Analysis of team roster construction and needs"""
    __tablename__ = "team_needs_analysis"
    
    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("fantasy_teams.id"), nullable=False)
    week = Column(Integer, nullable=False)
    season = Column(Integer, nullable=False)
    
    # Position strength analysis
    position_strengths = Column(JSON)  # {"QB": 8.5, "RB": 6.2, ...} out of 10
    position_needs = Column(JSON)  # {"RB": 3, "WR": 1, ...} need level 0-5
    
    # Roster construction
    starter_quality = Column(Float)  # Average starter quality 0-10
    bench_depth = Column(Float)  # Bench depth score 0-10
    age_profile = Column(Float)  # Average age of key players
    
    # Strategic analysis
    championship_contender = Column(Boolean, default=False)
    should_rebuild = Column(Boolean, default=False)
    win_now_mode = Column(Boolean, default=False)
    
    # Trade preferences
    preferred_trade_types = Column(JSON)  # ["consolidate", "depth", "youth", etc.]
    assets_to_sell = Column(JSON)  # Player IDs that should be traded away
    targets_to_acquire = Column(JSON)  # Position/player types to target
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    team = relationship("FantasyTeam")

# Create indexes for better performance
from sqlalchemy import Index

# Add indexes for common queries
Index('idx_fantasy_user_platform', FantasyUser.user_id, FantasyUser.platform)
Index('idx_fantasy_league_sync', FantasyLeague.fantasy_user_id, FantasyLeague.is_synced)
Index('idx_roster_team_week', FantasyRosterSpot.team_id, FantasyRosterSpot.week)
Index('idx_projections_player_week', PlayerProjection.player_id, PlayerProjection.week, PlayerProjection.season)
Index('idx_recommendations_user_active', FantasyRecommendation.user_id, FantasyRecommendation.is_active)
Index('idx_waiver_targets_league_week', WaiverWireTarget.league_id, WaiverWireTarget.week)
Index('idx_historical_data_league_season', LeagueHistoricalData.league_id, LeagueHistoricalData.season)
Index('idx_competitor_analysis_league_team', CompetitorAnalysis.league_id, CompetitorAnalysis.team_id)
Index('idx_player_analytics_player_week', PlayerAnalytics.player_id, PlayerAnalytics.week, PlayerAnalytics.season)
Index('idx_player_trends_player_season', PlayerTrends.player_id, PlayerTrends.season)
Index('idx_player_analytics_snap_share', PlayerAnalytics.player_id, PlayerAnalytics.snap_percentage)
Index('idx_player_analytics_target_share', PlayerAnalytics.player_id, PlayerAnalytics.target_share)
Index('idx_draft_picks_league_season', DraftPick.league_id, DraftPick.season)
Index('idx_trades_league_status', Trade.league_id, Trade.status)
Index('idx_trades_teams', Trade.team1_id, Trade.team2_id)
Index('idx_trade_evaluations_trade', TradeEvaluation.trade_id)
Index('idx_trade_recommendations_active', TradeRecommendation.league_id, TradeRecommendation.is_active)
Index('idx_player_values_league_week', PlayerValue.league_id, PlayerValue.week, PlayerValue.season)
Index('idx_team_needs_analysis_team_week', TeamNeedsAnalysis.team_id, TeamNeedsAnalysis.week)