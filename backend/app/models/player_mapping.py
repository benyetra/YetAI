"""
Player ID Mapping Model
Central source of truth for player IDs across all platforms
"""
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Date, Text, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base

class PlayerIDMapping(Base):
    """Central mapping table for player IDs across all platforms"""
    __tablename__ = "player_id_mappings"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Internal YetAI ID (our primary key reference)
    yetai_id = Column(Integer, ForeignKey("fantasy_players.id", ondelete="CASCADE"), nullable=False, unique=True)
    
    # External Platform IDs
    sleeper_id = Column(String(50), index=True)
    espn_id = Column(String(50), index=True)
    yahoo_id = Column(String(50), index=True)
    draftkings_id = Column(String(50), index=True)
    fanduel_id = Column(String(50), index=True)
    nfl_id = Column(String(50), index=True)
    pfr_id = Column(String(50))  # Pro Football Reference
    rotowire_id = Column(String(50))
    numberfire_id = Column(String(50))
    sportradar_id = Column(String(50))
    
    # Player identifiers for matching
    full_name = Column(String(255), nullable=False, index=True)
    first_name = Column(String(100))
    last_name = Column(String(100))
    suffix = Column(String(10))  # Jr., Sr., III, etc.
    
    # Additional matching fields
    birth_date = Column(Date)
    college = Column(String(100))
    draft_year = Column(Integer)
    draft_round = Column(Integer)
    draft_pick = Column(Integer)
    
    # Position and team (current)
    position = Column(String(10))
    team = Column(String(10))
    jersey_number = Column(Integer)
    
    # Status flags
    is_active = Column(Boolean, default=True)
    is_rookie = Column(Boolean, default=False)
    is_verified = Column(Boolean, default=False)
    confidence_score = Column(Float, default=0.0)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_sync_at = Column(DateTime)
    notes = Column(Text)
    
    # Relationship to fantasy player
    fantasy_player = relationship("FantasyPlayer", backref="id_mapping", uselist=False)