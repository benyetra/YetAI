"""List and fetch persisted fantasy trade proposals for the authenticated user."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.fantasy_models import (
    FantasyLeague,
    FantasyPlatform,
    FantasyTeam,
    FantasyUser,
    Trade,
    TradeEvaluation,
)


def _resolve_user_league(
    db: Session, *, user_id: int, platform_league_id: str
) -> Optional[FantasyLeague]:
    return (
        db.query(FantasyLeague)
        .join(FantasyUser, FantasyLeague.fantasy_user_id == FantasyUser.id)
        .filter(
            FantasyUser.user_id == user_id,
            FantasyLeague.platform == FantasyPlatform.SLEEPER,
            FantasyLeague.platform_league_id == str(platform_league_id),
        )
        .first()
    )


def _team_summary(team: Optional[FantasyTeam]) -> Dict[str, Any]:
    if team is None:
        return {"id": None, "roster_id": None, "name": "Unknown"}
    roster_id = None
    try:
        roster_id = int(team.platform_team_id)
    except (TypeError, ValueError):
        roster_id = team.platform_team_id
    return {
        "id": team.id,
        "roster_id": roster_id,
        "name": team.name,
        "owner_name": team.owner_name,
    }


def _assets_summary(assets: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    assets = assets or {}
    players = assets.get("players") or []
    picks = assets.get("picks") or []
    faab = assets.get("faab") or 0
    return {
        "player_count": len(players),
        "pick_count": len(picks),
        "faab": faab,
        "players": players,
        "picks": picks,
    }


def _evaluation_summary(
    evaluation: Optional[TradeEvaluation],
) -> Optional[Dict[str, Any]]:
    if evaluation is None:
        return None
    return {
        "fairness_score": evaluation.fairness_score,
        "team1_grade": (
            evaluation.team1_grade.value if evaluation.team1_grade else None
        ),
        "team2_grade": (
            evaluation.team2_grade.value if evaluation.team2_grade else None
        ),
        "ai_summary": evaluation.ai_summary,
        "confidence": evaluation.confidence,
    }


def _serialize_trade_summary(trade: Trade) -> Dict[str, Any]:
    evaluation = trade.evaluations[0] if trade.evaluations else None
    return {
        "trade_id": trade.id,
        "status": trade.status.value if trade.status else None,
        "proposed_at": trade.proposed_at.isoformat() if trade.proposed_at else None,
        "expires_at": trade.expires_at.isoformat() if trade.expires_at else None,
        "trade_reason": trade.trade_reason,
        "team1": _team_summary(trade.team1),
        "team2": _team_summary(trade.team2),
        "team1_gives": _assets_summary(trade.team1_gives),
        "team2_gives": _assets_summary(trade.team2_gives),
        "evaluation": _evaluation_summary(evaluation),
    }


def _serialize_trade_detail(trade: Trade) -> Dict[str, Any]:
    summary = _serialize_trade_summary(trade)
    evaluation = trade.evaluations[0] if trade.evaluations else None
    if evaluation is not None:
        summary["evaluation_detail"] = {
            "evaluation_id": evaluation.id,
            "grades": {
                "team1_grade": (
                    evaluation.team1_grade.value if evaluation.team1_grade else None
                ),
                "team2_grade": (
                    evaluation.team2_grade.value if evaluation.team2_grade else None
                ),
            },
            "values": {
                "team1_value_given": evaluation.team1_value_given,
                "team1_value_received": evaluation.team1_value_received,
                "team2_value_given": evaluation.team2_value_given,
                "team2_value_received": evaluation.team2_value_received,
            },
            "analysis": {
                "team1_analysis": evaluation.team1_analysis,
                "team2_analysis": evaluation.team2_analysis,
            },
            "fairness_score": evaluation.fairness_score,
            "ai_summary": evaluation.ai_summary,
            "key_factors": evaluation.key_factors,
            "confidence": evaluation.confidence,
            "trade_context": evaluation.trade_context,
            "created_at": (
                evaluation.created_at.isoformat() if evaluation.created_at else None
            ),
        }
    return summary


def list_trade_proposals(
    db: Session,
    *,
    user_id: int,
    platform_league_id: str,
    limit: int = 50,
) -> Dict[str, Any]:
    """Return saved trade proposals for a Sleeper league owned by the user."""
    league = _resolve_user_league(
        db, user_id=user_id, platform_league_id=platform_league_id
    )
    if league is None:
        return {
            "success": False,
            "error": "League not found or not linked to your account",
            "proposals": [],
        }

    trades = (
        db.query(Trade)
        .filter(Trade.league_id == league.id)
        .order_by(Trade.proposed_at.desc(), Trade.id.desc())
        .limit(max(1, min(limit, 100)))
        .all()
    )

    return {
        "success": True,
        "league_id": platform_league_id,
        "proposals": [_serialize_trade_summary(trade) for trade in trades],
        "total": len(trades),
    }


def get_trade_proposal(
    db: Session,
    *,
    user_id: int,
    trade_id: int,
) -> Dict[str, Any]:
    """Return one persisted trade proposal if the user owns the parent league."""
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if trade is None:
        return {"success": False, "error": "Trade not found"}

    league = (
        db.query(FantasyLeague)
        .join(FantasyUser, FantasyLeague.fantasy_user_id == FantasyUser.id)
        .filter(
            FantasyLeague.id == trade.league_id,
            FantasyUser.user_id == user_id,
        )
        .first()
    )
    if league is None:
        return {"success": False, "error": "Trade not found"}

    payload = _serialize_trade_detail(trade)
    payload["success"] = True
    payload["league_id"] = league.platform_league_id
    return payload
