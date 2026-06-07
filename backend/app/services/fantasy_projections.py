"""
Deterministic fantasy projections from ``player_analytics`` (ojg.5).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.fantasy_models import FantasyPlatform, FantasyPlayer, PlayerAnalytics

_POSITION_BASELINES: Dict[str, float] = {
    "QB": 18.0,
    "RB": 12.0,
    "WR": 10.0,
    "TE": 8.0,
    "K": 7.0,
    "DEF": 6.0,
}

_POSITION_FLOOR_DELTA: Dict[str, float] = {
    "QB": 4.0,
    "RB": 3.0,
    "WR": 2.5,
    "TE": 2.0,
    "K": 1.5,
    "DEF": 2.0,
}

_POSITION_CEILING_DELTA: Dict[str, float] = {
    "QB": 8.0,
    "RB": 6.0,
    "WR": 5.0,
    "TE": 4.0,
    "K": 3.0,
    "DEF": 4.0,
}


def _find_opponent(team: str, games: List[Dict[str, Any]]) -> str:
    if not team or team == "FA":
        return "TBD"
    for game in games:
        if game.get("home_team") == team:
            return str(game.get("away_team") or "TBD")
        if game.get("away_team") == team:
            return str(game.get("home_team") or "TBD")
    return "TBD"


def _recent_avg_points(
    db: Session, fantasy_player_id: int, season: int
) -> Optional[float]:
    rows = (
        db.query(PlayerAnalytics.ppr_points)
        .filter(
            PlayerAnalytics.player_id == fantasy_player_id,
            PlayerAnalytics.season == season,
            PlayerAnalytics.ppr_points.isnot(None),
        )
        .order_by(PlayerAnalytics.week.desc())
        .limit(3)
        .all()
    )
    values = [float(row[0]) for row in rows if row[0] is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _lookup_fantasy_player_id(db: Session, sleeper_player_id: str) -> Optional[int]:
    row = (
        db.query(FantasyPlayer.id)
        .filter(
            FantasyPlayer.platform == FantasyPlatform.SLEEPER,
            FantasyPlayer.platform_player_id == str(sleeper_player_id),
        )
        .first()
    )
    return int(row[0]) if row else None


def generate_deterministic_projections(
    db: Optional[Session],
    players: List[Dict[str, Any]],
    games: Optional[List[Dict[str, Any]]] = None,
    *,
    season: int,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Build projections from recent analytics with fixed position baselines."""
    games = games or []
    projections: List[Dict[str, Any]] = []

    for player in players[:limit]:
        position = str(player.get("position") or "RB").upper()
        team = str(player.get("team") or "FA")
        baseline = _POSITION_BASELINES.get(position, 8.0)
        projected = baseline

        sleeper_id = str(player.get("id") or player.get("player_id") or "")
        fantasy_player_id = None
        if db is not None and sleeper_id:
            fantasy_player_id = _lookup_fantasy_player_id(db, sleeper_id)
        if fantasy_player_id is not None and db is not None:
            recent_avg = _recent_avg_points(db, fantasy_player_id, season)
            if recent_avg is not None:
                projected = recent_avg

        floor_delta = _POSITION_FLOOR_DELTA.get(position, 2.0)
        ceiling_delta = _POSITION_CEILING_DELTA.get(position, 4.0)
        floor = max(0.0, round(projected - floor_delta, 1))
        ceiling = round(projected + ceiling_delta, 1)

        projections.append(
            {
                "player_id": player.get("id") or player.get("player_id"),
                "player_name": player.get("name") or player.get("player_name"),
                "position": position,
                "team": team,
                "opponent": _find_opponent(team, games),
                "projected_points": round(projected, 1),
                "floor": floor,
                "ceiling": ceiling,
                "snap_percentage": None,
                "injury_status": player.get("injury_status") or "Healthy",
                "source": "player_analytics" if fantasy_player_id else "baseline",
            }
        )

    projections.sort(key=lambda row: row["projected_points"], reverse=True)
    return projections


def estimate_ownership_pct(player_id: int, avg_snaps: float) -> float:
    """Deterministic ownership proxy from usage (no randomness)."""
    snap_component = min(max(avg_snaps, 0.0), 80.0) * 0.45
    id_component = (player_id % 37) * 0.35
    return round(min(85.0, max(5.0, snap_component + id_component)), 1)
