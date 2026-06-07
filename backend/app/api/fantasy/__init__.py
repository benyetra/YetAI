"""Aggregate fantasy routers for main app registration."""

from fastapi import APIRouter

from app.api.fantasy.connect import router as connect_router
from app.api.fantasy.leagues import router as leagues_router
from app.api.fantasy.legacy_analytics import router as legacy_analytics_router
from app.api.fantasy.matchups import router as matchups_router
from app.api.fantasy.players import router as players_router
from app.api.fantasy.recommendations import router as recommendations_router
from app.api.fantasy.trade_analyzer import router as trade_analyzer_router

router = APIRouter()
router.include_router(connect_router)
router.include_router(players_router)
router.include_router(recommendations_router)
router.include_router(leagues_router)
router.include_router(legacy_analytics_router)
router.include_router(trade_analyzer_router)
router.include_router(matchups_router)
