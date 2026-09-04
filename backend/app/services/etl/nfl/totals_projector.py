"""NFL game totals (O/U) projections — PPG blend with spread-aligned scores."""

from __future__ import annotations

import logging
from datetime import datetime

from app.core.database import SessionLocal
from app.models.predictions_models import (
    NFLGameLines,
    NFLSpreadActuals,
    NFLTotalsProjections,
)
from app.services.etl.nba._espn import now_eastern
from app.services.etl.nfl._team_ppg import compute_team_ppg_stats, team_ppg_for
from app.services.etl.nfl.spread_projector import (
    _load_elos,
    _load_qb_out_by_team,
    _project_spread_row,
    projection_end_date,
)
from app.services.etl.wnba._db_upsert import upsert_many

logger = logging.getLogger(__name__)

TOTALS_EDGE_THRESHOLD = 3.0


def _project_matchup_score(off_ppg: float, opp_def_ppg: float) -> float:
    """Blend offensive and opposing defensive scoring rates."""
    return (off_ppg + opp_def_ppg) / 2.0


def _project_total_from_ppg(
    home_team_name: str,
    away_team_name: str,
    ppg_stats: dict[str, tuple[float, float]],
) -> tuple[float, float, float, float, float, float, float]:
    home_off, home_def = team_ppg_for(home_team_name, ppg_stats)
    away_off, away_def = team_ppg_for(away_team_name, ppg_stats)

    home_raw = _project_matchup_score(home_off, away_def)
    away_raw = _project_matchup_score(away_off, home_def)
    projected_total = home_raw + away_raw

    return (
        projected_total,
        home_raw,
        away_raw,
        home_off,
        away_off,
        home_def,
        away_def,
    )


def _align_scores(
    projected_margin: float, projected_total: float
) -> tuple[float, float]:
    """Split total into team scores consistent with home-perspective margin."""
    home_pts = (projected_total + projected_margin) / 2.0
    away_pts = (projected_total - projected_margin) / 2.0
    return home_pts, away_pts


def _totals_recommendation(
    projected_total: float,
    market_total: float | None,
    *,
    threshold: float = TOTALS_EDGE_THRESHOLD,
) -> tuple[float | None, str]:
    if market_total is None:
        return None, "NO_PLAY"
    edge = projected_total - market_total
    if edge >= threshold:
        return edge, "OVER"
    if market_total - projected_total >= threshold:
        return edge, "UNDER"
    return edge, "NO_PLAY"


def _project_totals_row(
    *,
    home_team_name: str,
    away_team_name: str,
    spread_home: float | None,
    market_total: float | None,
    elos: dict[str, float],
    ppg_stats: dict[str, tuple[float, float]],
    home_qb_out: bool = False,
    away_qb_out: bool = False,
) -> dict:
    spread = _project_spread_row(
        home_team_name=home_team_name,
        away_team_name=away_team_name,
        spread_home=spread_home,
        elos=elos,
        ppg_stats=ppg_stats,
        home_qb_out=home_qb_out,
        away_qb_out=away_qb_out,
    )
    projected_margin = spread["projected_margin"]

    (
        projected_total,
        home_raw,
        away_raw,
        home_off,
        away_off,
        home_def,
        away_def,
    ) = _project_total_from_ppg(home_team_name, away_team_name, ppg_stats)

    home_pts, away_pts = _align_scores(projected_margin, projected_total)
    edge, recommendation = _totals_recommendation(projected_total, market_total)

    return {
        "projected_total": projected_total,
        "home_projected_score": home_pts,
        "away_projected_score": away_pts,
        "base_projection": home_raw + away_raw,
        "home_offensive_rating": home_off,
        "away_offensive_rating": away_off,
        "home_defensive_rating": home_def,
        "away_defensive_rating": away_def,
        "market_total": market_total,
        "edge": edge,
        "recommendation": recommendation,
        "confidence_score": (min(1.0, abs(edge) / 6.0) if edge is not None else None),
        "factors": {
            "projected_margin": projected_margin,
            "home_raw": home_raw,
            "away_raw": away_raw,
            "method": "ppg_blend",
        },
    }


def run() -> dict:
    today = now_eastern().date()
    end = projection_end_date(today)

    db = SessionLocal()
    upsert_rows: list[dict] = []
    try:
        elos = _load_elos(db)
        actuals = (
            db.query(NFLSpreadActuals).order_by(NFLSpreadActuals.game_date.asc()).all()
        )
        ppg_stats = compute_team_ppg_stats(actuals)
        qb_out_by_team = _load_qb_out_by_team(db)

        games = (
            db.query(NFLGameLines)
            .filter(NFLGameLines.game_date >= today, NFLGameLines.game_date <= end)
            .all()
        )

        for g in games:
            projection = _project_totals_row(
                home_team_name=g.home_team_name,
                away_team_name=g.away_team_name,
                spread_home=g.spread_home,
                market_total=g.total,
                elos=elos,
                ppg_stats=ppg_stats,
                home_qb_out=qb_out_by_team.get(g.home_team_name, False),
                away_qb_out=qb_out_by_team.get(g.away_team_name, False),
            )
            upsert_rows.append(
                {
                    "game_date": g.game_date,
                    "home_team_id": g.home_team_id,
                    "away_team_id": g.away_team_id,
                    "home_team_name": g.home_team_name,
                    "away_team_name": g.away_team_name,
                    "created_at": datetime.utcnow(),
                    **projection,
                }
            )

        upsert_many(
            db,
            NFLTotalsProjections,
            upsert_rows,
            conflict_keys=["game_date", "home_team_name", "away_team_name"],
        )
        db.commit()
        return {"status": "ok", "games": len(upsert_rows)}
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
