from __future__ import annotations

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base


class TimestampMixin:
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class BppGameSnapshot(TimestampMixin, Base):
    __tablename__ = "bpp_game_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "slate_date", "bpp_game_id", name="uq_bpp_game_snapshot_date_game"
        ),
    )

    id = Column(Integer, primary_key=True)
    slate_date = Column(Date, nullable=False)
    bpp_game_id = Column(Integer, nullable=False)
    game_pk = Column(Integer, nullable=True)
    team_away_id = Column(Integer, nullable=False)
    team_home_id = Column(Integer, nullable=False)
    as_of = Column(DateTime(timezone=True), nullable=False)
    averages_json = Column(JSON, nullable=False)
    probabilities_json = Column(JSON, nullable=False)


class BppPlayerProjSnapshot(TimestampMixin, Base):
    __tablename__ = "bpp_player_proj_snapshots"
    __table_args__ = (
        CheckConstraint(
            "role IN ('batter', 'pitcher', 'team')",
            name="ck_bpp_player_proj_snapshot_role",
        ),
        UniqueConstraint(
            "slate_date",
            "bpp_game_id",
            "player_id",
            "role",
            name="uq_bpp_player_proj_snapshot_date_game_player_role",
        ),
    )

    id = Column(Integer, primary_key=True)
    slate_date = Column(Date, nullable=False)
    bpp_game_id = Column(Integer, nullable=False)
    game_pk = Column(Integer, nullable=False)
    player_id = Column(Integer, nullable=False)
    team_id = Column(Integer, nullable=False)
    role = Column(String(16), nullable=False)
    averages_json = Column(JSON, nullable=False)
    selected_probs_json = Column(JSON, nullable=False)


class BppParkFactorSnapshot(TimestampMixin, Base):
    __tablename__ = "bpp_park_factor_snapshots"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('game', 'hitter')",
            name="ck_bpp_park_factor_snapshot_scope",
        ),
        UniqueConstraint(
            "slate_date",
            "bpp_game_id",
            "scope",
            "player_id",
            name="uq_bpp_park_factor_snapshot_date_game_scope_player",
        ),
    )

    id = Column(Integer, primary_key=True)
    slate_date = Column(Date, nullable=False)
    bpp_game_id = Column(Integer, nullable=False)
    game_pk = Column(Integer, nullable=False)
    scope = Column(String(16), nullable=False)
    player_id = Column(Integer, nullable=False, default=0)
    factors_json = Column(JSON, nullable=False)


class BppMatchupSnapshot(TimestampMixin, Base):
    __tablename__ = "bpp_matchup_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "slate_date",
            "batter_id",
            "pitcher_id",
            name="uq_bpp_matchup_snapshot_date_batter_pitcher",
        ),
    )

    id = Column(Integer, primary_key=True)
    slate_date = Column(Date, nullable=False)
    bpp_game_id = Column(Integer, nullable=False)
    game_pk = Column(Integer, nullable=False)
    batter_id = Column(Integer, nullable=False)
    pitcher_id = Column(Integer, nullable=False)
    probs_json = Column(JSON, nullable=False)
