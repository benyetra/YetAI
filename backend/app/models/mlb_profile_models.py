from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class MlbPitcherProfileSnapshot(Base):
    __tablename__ = "mlb_pitcher_profile_snapshots"

    id = Column(Integer, primary_key=True)
    pitcher_id = Column(Integer, nullable=False, index=True)
    as_of_date = Column(Date, nullable=False, index=True)
    window = Column(String(16), nullable=False)  # 7d | 30d | season | 3yr_decay
    profile_version = Column(String(32), nullable=False)
    hand = Column(String(1), nullable=True)
    n_pitches = Column(Integer, nullable=False, default=0)
    profile = Column(JSONB, nullable=False)  # usage, location, velo, ...
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "pitcher_id",
            "as_of_date",
            "window",
            "profile_version",
            name="uq_mlb_pitcher_profile_snapshot",
        ),
    )


class MlbBatterProfileSnapshot(Base):
    __tablename__ = "mlb_batter_profile_snapshots"

    id = Column(Integer, primary_key=True)
    batter_id = Column(Integer, nullable=False, index=True)
    vs_hand = Column(String(1), nullable=False)  # L | R
    as_of_date = Column(Date, nullable=False, index=True)
    window = Column(String(16), nullable=False)
    profile_version = Column(String(32), nullable=False)
    n_pitches = Column(Integer, nullable=False, default=0)
    profile = Column(JSONB, nullable=False)  # whiff_by_pitch, cold_zones, ...
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "batter_id",
            "vs_hand",
            "as_of_date",
            "window",
            "profile_version",
            name="uq_mlb_batter_profile_snapshot",
        ),
    )
