"""Build side-by-side fantasy player comparisons with analytics and insights."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.player_analytics_service import PlayerAnalyticsService


def scoring_type_from_sleeper_league(league: Optional[Dict[str, Any]]) -> str:
    """Map Sleeper scoring_settings.rec to ppr / half_ppr / standard."""
    if not league:
        return "ppr"
    rec = float((league.get("scoring_settings") or {}).get("rec", 1))
    if rec >= 1:
        return "ppr"
    if rec >= 0.5:
        return "half_ppr"
    return "standard"


def _points_field_for_scoring(scoring_type: str) -> str:
    normalized = (scoring_type or "ppr").lower().replace("-", "_")
    if normalized in {"half_ppr", "half"}:
        return "half_ppr_points"
    if normalized == "standard":
        return "standard_points"
    return "ppr_points"


def _scoring_label(scoring_type: str) -> str:
    normalized = (scoring_type or "ppr").lower().replace("-", "_")
    if normalized in {"half_ppr", "half"}:
        return "Half PPR"
    if normalized == "standard":
        return "Standard"
    return "PPR"


def _aggregate_analytics(
    weekly_rows: List[Dict[str, Any]], *, points_field: str = "ppr_points"
) -> Dict[str, Any]:
    valid = [r for r in weekly_rows if r]
    if not valid:
        return {}

    games = len(valid)
    total_points = sum(r.get(points_field) or r.get("ppr_points") or 0 for r in valid)
    total_carries = sum(r.get("carries") or 0 for r in valid)
    total_targets = sum(r.get("targets") or 0 for r in valid)
    total_rush_yards = sum(r.get("rushing_yards") or 0 for r in valid)
    total_touches = total_carries + total_targets

    point_values = [r.get(points_field) or r.get("ppr_points") or 0 for r in valid]
    mean_points = total_points / games if games else 0
    variance = sum((v - mean_points) ** 2 for v in point_values) / games if games else 0
    consistency = max(0, 1 - (variance**0.5 / mean_points)) if mean_points > 0 else 0

    def avg(field: str) -> float:
        return sum(r.get(field) or 0 for r in valid) / games

    return {
        "snap_percentage": avg("snap_percentage"),
        "target_share": avg("target_share"),
        "red_zone_share": avg("red_zone_share"),
        "points_per_snap": avg("points_per_snap"),
        "points_per_target": avg("points_per_target"),
        "boom_rate": avg("boom_rate"),
        "bust_rate": avg("bust_rate"),
        "floor_score": avg("floor_score"),
        "ceiling_score": avg("ceiling_score"),
        "points_per_touch": total_points / total_touches if total_touches else 0,
        "touches_per_game": total_touches / games,
        "rush_yards_per_game": total_rush_yards / games,
        "yards_per_carry": total_rush_yards / total_carries if total_carries else 0,
        "consistency_score": consistency,
    }


def _derive_trends(
    weekly_rows: List[Dict[str, Any]], *, points_field: str = "ppr_points"
) -> Dict[str, Any]:
    ordered = sorted(weekly_rows, key=lambda r: r.get("week") or 0, reverse=True)
    if len(ordered) < 2:
        return {}

    recent = ordered[:3]
    older = ordered[3:6]
    if not older:
        return {}

    def row_points(row: Dict[str, Any]) -> float:
        return float(row.get(points_field) or row.get("ppr_points") or 0)

    recent_avg = sum(row_points(r) for r in recent) / len(recent)
    older_avg = sum(row_points(r) for r in older) / len(older)
    return {
        "trend_direction": "up" if recent_avg > older_avg else "down",
        "recent_avg": round(recent_avg, 1),
        "previous_avg": round(older_avg, 1),
        "games_analyzed": len(recent) + len(older),
    }


def _lookup_internal_player_id(db: Session, sleeper_id: str) -> Optional[int]:
    row = db.execute(
        text("SELECT id FROM fantasy_players WHERE platform_player_id = :sleeper_id"),
        {"sleeper_id": str(sleeper_id)},
    ).fetchone()
    return int(row[0]) if row else None


def generate_compare_insights(
    players: List[Dict[str, Any]], *, scoring_type: str = "ppr"
) -> List[str]:
    """Human-readable insights from enriched comparison players."""
    if len(players) < 2:
        return []

    insights: List[str] = []
    scoring_label = _scoring_label(scoring_type)

    def best_by(key: str, label: str, *, higher_is_better: bool = True) -> None:
        values = [
            (p, (p.get("analytics") or {}).get(key))
            for p in players
            if (p.get("analytics") or {}).get(key) is not None
        ]
        if len(values) < 2:
            return
        winner = (
            max(values, key=lambda x: x[1] or 0)
            if higher_is_better
            else min(values, key=lambda x: x[1] or 0)
        )
        runner = sorted(values, key=lambda x: x[1] or 0, reverse=higher_is_better)[1]
        if winner[1] == runner[1]:
            return
        insights.append(f"{winner[0]['name']} leads in {label} ({winner[1]:.1f}).")

    best_by("points_per_game", f"scoring ({scoring_label} PPG)", higher_is_better=True)
    best_by("snap_percentage", "snap share (%)", higher_is_better=True)
    best_by("target_share", "target share", higher_is_better=True)
    best_by("consistency_score", "consistency", higher_is_better=True)
    best_by("ceiling_score", "ceiling", higher_is_better=True)

    trending_up = [
        p for p in players if (p.get("trends") or {}).get("trend_direction") == "up"
    ]
    if len(trending_up) == 1:
        insights.append(f"{trending_up[0]['name']} is trending up recently.")
    elif len(trending_up) > 1:
        names = ", ".join(p["name"] for p in trending_up)
        insights.append(f"Recent scoring uptrend: {names}.")

    injured = [
        p for p in players if p.get("injury_status") not in (None, "", "Healthy")
    ]
    if injured:
        names = ", ".join(p["name"] for p in injured)
        insights.append(f"Injury flag on: {names}.")

    return insights[:8]


async def enrich_players_with_analytics(
    db: Session,
    players: List[Dict[str, Any]],
    *,
    season: int = 2025,
    scoring_type: str = "ppr",
) -> List[Dict[str, Any]]:
    """Attach season analytics, trends, and season_stats to comparison players."""
    analytics_service = PlayerAnalyticsService(db)
    points_field = _points_field_for_scoring(scoring_type)
    enriched: List[Dict[str, Any]] = []

    for player in players:
        sleeper_id = str(player.get("player_id", ""))
        internal_id = _lookup_internal_player_id(db, sleeper_id)
        copy = dict(player)

        if not internal_id:
            copy.update(
                analytics={},
                season_stats={},
                trends={},
                efficiency={},
            )
            enriched.append(copy)
            continue

        weekly = await analytics_service.get_player_analytics(
            internal_id, season=season
        )
        agg = _aggregate_analytics(weekly, points_field=points_field)
        trends = _derive_trends(weekly, points_field=points_field)

        games = len([w for w in weekly if w])
        total_points = sum(
            w.get(points_field) or w.get("ppr_points") or 0 for w in weekly
        )
        season_stats = {
            "points_per_game": total_points / games if games else 0,
            "games_played": games,
            "total_points": total_points,
            "scoring_format": scoring_type,
        }
        if season_stats["points_per_game"]:
            agg["points_per_game"] = season_stats["points_per_game"]

        copy.update(
            analytics=agg,
            season_stats=season_stats,
            trends=trends,
            efficiency={},
        )
        enriched.append(copy)

    return enriched
