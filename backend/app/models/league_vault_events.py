"""Public vault analytics beacons — league-attributed page views for the pilot."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base


class LvVaultEvent(Base):
    """Anonymous page-view / engagement events keyed by vault site."""

    __tablename__ = "lv_vault_events"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("lv_sites.id"), nullable=False, index=True)
    slug = Column(String(128), nullable=False, index=True)
    path = Column(String(512), nullable=False)
    event_type = Column(String(64), nullable=False, default="page_view")
    referrer = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
