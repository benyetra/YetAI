"""Backward-compatible re-export; routes live in ``app.api.fantasy.matchups``."""

from app.api.fantasy.matchups import router

__all__ = ["router"]
