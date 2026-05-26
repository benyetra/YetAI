from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint

from app.core.database import Base


class MlbPlayerArchetype(Base):
    """Season-level batter archetype assignment for cold-start priors (Phase 6)."""

    __tablename__ = "mlb_player_archetypes"

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, nullable=False, index=True)
    season = Column(Integer, nullable=False, index=True)
    archetype_id = Column(String(32), nullable=False)
    n_pitches = Column(Integer, nullable=False, default=0)
    assigned_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("player_id", "season", name="uq_mlb_player_archetype_season"),
    )
