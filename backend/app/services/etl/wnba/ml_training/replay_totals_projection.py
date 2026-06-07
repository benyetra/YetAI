"""Point-in-time replay of WNBA totals projections for ML training backfill."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.services.etl.wnba import totals_projector as tp
from app.services.etl.wnba.ml_training import team_stats_as_of as tsa
from app.services.etl.wnba.ml_training.totals_backfill_context import (
    TotalsBackfillContext,
    form_adjustment_as_of as ctx_form_adjustment_as_of,
    rest_adjustment_as_of as ctx_rest_adjustment_as_of,
)


def generate_projection_as_of(
    *,
    home_team: str,
    away_team: str,
    game_date: date,
    market_total: float | None,
    stats_cache: tsa.TeamStatsCache,
    include_injury: bool = False,
    backfill_ctx: TotalsBackfillContext | None = None,
) -> dict[str, Any]:
    """
    Full heuristic totals projection aligned with production logic.

    Uses point-in-time pace/efficiency and form/rest adjustments. Injury impact is
    off by default for historical backfill (injury table reflects current status).
    """
    home_stats = tsa.pace_and_efficiency_as_of(stats_cache, home_team, game_date)
    away_stats = tsa.pace_and_efficiency_as_of(stats_cache, away_team, game_date)

    expected_pace = tp.estimate_game_pace(home_stats["pace"], away_stats["pace"])
    home_adj_ortg = tp.matchup_efficiency(
        home_stats["offensive_rating"], away_stats["defensive_rating"]
    )
    away_adj_ortg = tp.matchup_efficiency(
        away_stats["offensive_rating"], home_stats["defensive_rating"]
    )
    home_projected = tp.project_team_score(home_adj_ortg, expected_pace)
    away_projected = tp.project_team_score(away_adj_ortg, expected_pace)
    base_projection = home_projected + away_projected

    injury_adjustment = 0.0
    injury_report: dict[str, Any] = {}
    if include_injury:
        injury_adj_home, home_injuries = tp.calculate_injury_impact(
            home_team, game_date
        )
        injury_adj_away, away_injuries = tp.calculate_injury_impact(
            away_team, game_date
        )
        injury_adjustment = injury_adj_home + injury_adj_away
        if home_injuries:
            injury_report[home_team] = home_injuries
        if away_injuries:
            injury_report[away_team] = away_injuries

    if backfill_ctx is not None:
        rest_adjustment = ctx_rest_adjustment_as_of(
            backfill_ctx, home_team, away_team, game_date
        )
        form_adjustment = ctx_form_adjustment_as_of(
            backfill_ctx, home_team, away_team, game_date
        )
    else:
        rest_adjustment = tp.calculate_rest_adjustment(home_team, away_team, game_date)
        form_adjustment = tp.calculate_form_adjustment_as_of(
            home_team, away_team, game_date
        )
    venue_adjustment = tp.calculate_venue_adjustment(home_team)

    total_adjustment = (
        injury_adjustment + rest_adjustment + venue_adjustment + (form_adjustment * 0.3)
    )
    total_adjustment = max(-12.0, min(total_adjustment, 12.0))

    projected_total = base_projection + total_adjustment

    edge = None
    recommendation = "NO_PLAY"
    confidence = 0.5
    if market_total is not None:
        edge = projected_total - market_total
        if edge > 2:
            recommendation = "OVER"
            confidence = min(0.5 + (abs(edge) * 0.05), 0.85)
        elif edge < -2:
            recommendation = "UNDER"
            confidence = min(0.5 + (abs(edge) * 0.05), 0.85)

    factors: dict[str, Any] = {
        "pace_matchup": f"Expected {expected_pace:.1f} possessions",
        "backfill_source": "replay_as_of",
    }

    return {
        "game_date": game_date,
        "home_team": home_team,
        "away_team": away_team,
        "projected_total": round(projected_total, 1),
        "home_projected_score": round(home_projected + (total_adjustment / 2), 1),
        "away_projected_score": round(away_projected + (total_adjustment / 2), 1),
        "base_projection": round(base_projection, 1),
        "expected_pace": round(expected_pace, 1),
        "home_offensive_rating": round(home_stats["offensive_rating"], 1),
        "away_offensive_rating": round(away_stats["offensive_rating"], 1),
        "home_defensive_rating": round(home_stats["defensive_rating"], 1),
        "away_defensive_rating": round(away_stats["defensive_rating"], 1),
        "injury_adjustment": round(injury_adjustment, 1),
        "rest_adjustment": round(rest_adjustment, 1),
        "venue_adjustment": round(venue_adjustment, 1),
        "form_adjustment": round(form_adjustment * 0.3, 1),
        "total_adjustment": round(total_adjustment, 1),
        "market_total": market_total,
        "edge": round(edge, 1) if edge is not None else None,
        "recommendation": recommendation,
        "confidence_score": round(confidence, 2),
        "injury_report": injury_report or None,
        "factors": {
            **factors,
            "ml_shadow": {
                "heuristic_total": round(projected_total, 1),
                "ml_total": None,
            },
        },
        "home_starters": None,
        "away_starters": None,
    }


def projection_to_row(projection: dict[str, Any]) -> dict[str, Any]:
    """Map projection dict to ``pred_wnba_totals_projections`` upsert row."""
    from datetime import datetime

    return {
        "game_date": projection["game_date"],
        "home_team_id": tp.get_team_id_from_name(projection["home_team"]),
        "away_team_id": tp.get_team_id_from_name(projection["away_team"]),
        "home_team_name": projection["home_team"],
        "away_team_name": projection["away_team"],
        "projected_total": projection["projected_total"],
        "home_projected_score": projection["home_projected_score"],
        "away_projected_score": projection["away_projected_score"],
        "base_projection": projection["base_projection"],
        "expected_pace": projection["expected_pace"],
        "home_offensive_rating": projection["home_offensive_rating"],
        "away_offensive_rating": projection["away_offensive_rating"],
        "home_defensive_rating": projection["home_defensive_rating"],
        "away_defensive_rating": projection["away_defensive_rating"],
        "injury_adjustment": projection["injury_adjustment"],
        "rest_adjustment": projection["rest_adjustment"],
        "venue_adjustment": projection["venue_adjustment"],
        "form_adjustment": projection["form_adjustment"],
        "total_adjustment": projection["total_adjustment"],
        "market_total": projection["market_total"],
        "edge": projection["edge"],
        "recommendation": projection["recommendation"],
        "confidence_score": projection["confidence_score"],
        "injury_report": projection.get("injury_report"),
        "factors": projection.get("factors"),
        "home_starters": projection.get("home_starters"),
        "away_starters": projection.get("away_starters"),
        "created_at": datetime.utcnow(),
    }
