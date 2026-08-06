"""
SQLAlchemy models for League Vault pilot (lv_* tables).
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class LvLeagueLineage(Base):
    """Tracks a dynasty/redraft chain across seasons on one platform."""

    __tablename__ = "lv_league_lineage"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "root_platform_league_id",
            name="uq_lv_lineage_platform_root",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String(32), nullable=False)
    root_platform_league_id = Column(String(64), nullable=False)
    season_league_ids = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_synced = Column(DateTime, nullable=True)

    site = relationship("LvSite", back_populates="lineage", uselist=False)
    managers = relationship("LvManager", back_populates="lineage")
    seasons = relationship("LvSeason", back_populates="lineage")
    records = relationship("LvRecord", back_populates="lineage")
    sync_jobs = relationship("LvSyncJob", back_populates="lineage")


class LvSite(Base):
    """Public-facing site metadata for a league lineage."""

    __tablename__ = "lv_sites"

    id = Column(Integer, primary_key=True, index=True)
    lineage_id = Column(
        Integer, ForeignKey("lv_league_lineage.id"), nullable=False, unique=True
    )
    slug = Column(String(128), nullable=False, unique=True, index=True)
    display_name = Column(String(255), nullable=False)
    tagline = Column(String(512), nullable=True)
    first_season = Column(Integer, nullable=True)
    latest_season = Column(Integer, nullable=True)
    last_place_label = Column(String(64), nullable=True)
    is_public = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    lineage = relationship("LvLeagueLineage", back_populates="site")


class LvManager(Base):
    """Canonical manager identity within a lineage."""

    __tablename__ = "lv_managers"
    __table_args__ = (
        UniqueConstraint(
            "lineage_id",
            "platform_user_id",
            name="uq_lv_manager_lineage_platform_user",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    lineage_id = Column(Integer, ForeignKey("lv_league_lineage.id"), nullable=False)
    platform_user_id = Column(String(64), nullable=False)
    canonical_name = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=True)
    aliases = Column(JSON, nullable=False, default=list)
    first_season = Column(Integer, nullable=True)
    last_season = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    lineage = relationship("LvLeagueLineage", back_populates="managers")
    teams = relationship("LvTeam", back_populates="manager")


class LvSeason(Base):
    """One season snapshot for a lineage."""

    __tablename__ = "lv_seasons"
    __table_args__ = (
        UniqueConstraint("lineage_id", "season", name="uq_lv_season_lineage_season"),
    )

    id = Column(Integer, primary_key=True, index=True)
    lineage_id = Column(Integer, ForeignKey("lv_league_lineage.id"), nullable=False)
    season = Column(Integer, nullable=False)
    platform_league_id = Column(String(64), nullable=False)
    team_count = Column(Integer, nullable=True)
    playoff_teams = Column(Integer, nullable=True)
    regular_season_weeks = Column(Integer, nullable=True)
    scoring_settings = Column(JSON, nullable=True)
    roster_positions = Column(JSON, nullable=True)
    champion_manager_id = Column(Integer, ForeignKey("lv_managers.id"), nullable=True)
    runner_up_manager_id = Column(Integer, ForeignKey("lv_managers.id"), nullable=True)
    last_place_manager_id = Column(Integer, ForeignKey("lv_managers.id"), nullable=True)

    lineage = relationship("LvLeagueLineage", back_populates="seasons")
    teams = relationship(
        "LvTeam", back_populates="season", cascade="all, delete-orphan"
    )
    matchups = relationship(
        "LvMatchup", back_populates="season", cascade="all, delete-orphan"
    )
    transactions = relationship(
        "LvTransaction", back_populates="season", cascade="all, delete-orphan"
    )
    drafts = relationship(
        "LvDraft", back_populates="season", cascade="all, delete-orphan"
    )


class LvTeam(Base):
    """Team (roster) for a season."""

    __tablename__ = "lv_teams"
    __table_args__ = (
        UniqueConstraint(
            "season_id",
            "platform_roster_id",
            name="uq_lv_team_season_roster",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    season_id = Column(Integer, ForeignKey("lv_seasons.id"), nullable=False)
    manager_id = Column(Integer, ForeignKey("lv_managers.id"), nullable=False)
    platform_roster_id = Column(String(64), nullable=False)
    team_name = Column(String(255), nullable=True)
    avatar_url = Column(String(512), nullable=True)
    wins = Column(Integer, default=0, nullable=False)
    losses = Column(Integer, default=0, nullable=False)
    ties = Column(Integer, default=0, nullable=False)
    points_for = Column(Float, default=0.0, nullable=False)
    points_against = Column(Float, default=0.0, nullable=False)
    final_rank = Column(Integer, nullable=True)
    playoff_seed = Column(Integer, nullable=True)
    all_play_wins = Column(Integer, nullable=True)
    all_play_losses = Column(Integer, nullable=True)
    luck_differential = Column(Float, nullable=True)
    moves = Column(Integer, nullable=True)

    season = relationship("LvSeason", back_populates="teams")
    manager = relationship("LvManager", back_populates="teams")


class LvMatchup(Base):
    """Head-to-head matchup for a season week."""

    __tablename__ = "lv_matchups"

    id = Column(Integer, primary_key=True, index=True)
    season_id = Column(Integer, ForeignKey("lv_seasons.id"), nullable=False)
    week = Column(Integer, nullable=False)
    platform_matchup_id = Column(String(64), nullable=True)
    is_playoff = Column(Boolean, default=False, nullable=False)
    playoff_round = Column(Integer, nullable=True)
    bracket = Column(String(32), nullable=True)
    team_a_id = Column(Integer, ForeignKey("lv_teams.id"), nullable=False)
    team_b_id = Column(Integer, ForeignKey("lv_teams.id"), nullable=False)
    score_a = Column(Float, nullable=True)
    score_b = Column(Float, nullable=True)
    winner_team_id = Column(Integer, ForeignKey("lv_teams.id"), nullable=True)
    margin = Column(Float, nullable=True)

    season = relationship("LvSeason", back_populates="matchups")


class LvTransaction(Base):
    """Waiver/trade/free-agent transaction."""

    __tablename__ = "lv_transactions"
    __table_args__ = (
        UniqueConstraint(
            "season_id",
            "platform_transaction_id",
            name="uq_lv_tx_season_platform_id",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    season_id = Column(Integer, ForeignKey("lv_seasons.id"), nullable=False)
    week = Column(Integer, nullable=True)
    platform_transaction_id = Column(String(64), nullable=False)
    type = Column(String(64), nullable=False)
    status = Column(String(64), nullable=True)
    created_at_ts = Column(BigInteger, nullable=True)
    payload = Column(JSON, nullable=True)
    team_ids = Column(JSON, nullable=True)

    season = relationship("LvSeason", back_populates="transactions")


class LvDraft(Base):
    """Draft metadata for a season."""

    __tablename__ = "lv_drafts"

    id = Column(Integer, primary_key=True, index=True)
    season_id = Column(Integer, ForeignKey("lv_seasons.id"), nullable=False)
    platform_draft_id = Column(String(64), nullable=True)
    draft_type = Column(String(64), nullable=True)
    status = Column(String(64), nullable=True)
    settings = Column(JSON, nullable=True)

    season = relationship("LvSeason", back_populates="drafts")
    picks = relationship(
        "LvDraftPick", back_populates="draft", cascade="all, delete-orphan"
    )


class LvDraftPick(Base):
    """Individual draft pick."""

    __tablename__ = "lv_draft_picks"

    id = Column(Integer, primary_key=True, index=True)
    draft_id = Column(Integer, ForeignKey("lv_drafts.id"), nullable=False)
    round = Column(Integer, nullable=False)
    pick = Column(Integer, nullable=False)
    overall_pick = Column(Integer, nullable=True)
    platform_roster_id = Column(String(64), nullable=True)
    player_id = Column(String(64), nullable=True)
    team_id = Column(Integer, ForeignKey("lv_teams.id"), nullable=True)

    draft = relationship("LvDraft", back_populates="picks")


class LvRecord(Base):
    """Computed record-book entry (all-time or career scope)."""

    __tablename__ = "lv_records"

    id = Column(Integer, primary_key=True, index=True)
    lineage_id = Column(
        Integer, ForeignKey("lv_league_lineage.id"), nullable=False, index=True
    )
    record_key = Column(String(128), nullable=False, index=True)
    scope = Column(String(64), nullable=True)
    season = Column(Integer, nullable=True)
    manager_id = Column(Integer, ForeignKey("lv_managers.id"), nullable=True)
    team_id = Column(Integer, ForeignKey("lv_teams.id"), nullable=True)
    value = Column(Float, nullable=False)
    context = Column(JSON, nullable=True)
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    lineage = relationship("LvLeagueLineage", back_populates="records")


class LvSyncJob(Base):
    """Ingest/sync job audit trail."""

    __tablename__ = "lv_sync_jobs"

    id = Column(Integer, primary_key=True, index=True)
    lineage_id = Column(Integer, ForeignKey("lv_league_lineage.id"), nullable=True)
    platform = Column(String(32), nullable=False)
    root_platform_league_id = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    stats = Column(JSON, nullable=True)

    lineage = relationship("LvLeagueLineage", back_populates="sync_jobs")
