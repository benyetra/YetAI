"""NFL spread / win-probability projector (Elo + PPG overlay)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from app.core.database import SessionLocal
from app.models.predictions_models import (
    NFLGameLines,
    NFLSpreadActuals,
    NFLSpreadProjections,
    NFLTeamElo,
    QBPredictions,
)
from app.services.etl import _spread_model as _sm
from app.services.etl._spread_model import (
    NFL_CONFIG,
    load_elos_from_actuals,
    spread_recommendation,
)
from app.services.etl.nba._espn import now_eastern
from app.services.etl.nfl._team_ppg import compute_team_ppg_stats, team_ppg_for
from app.services.etl.nfl.nfl_common import get_current_nfl_week, get_nfl_season
from app.services.etl.nfl.qb_spread_adjustment import (
    qb_out_map_from_rows,
    qb_out_margin_adjustment,
)
from app.services.etl.nfl.update_game_lines import GAME_LINES_HORIZON_DAYS
from app.services.etl.wnba._db_upsert import upsert_many

logger = logging.getLogger(__name__)

INITIAL_ELO = NFL_CONFIG.initial_elo
HOME_COURT_ADVANTAGE = NFL_CONFIG.home_court_advantage


def projection_end_date(today: date) -> date:
    """Inclusive end of the game-board window; matches ``GAME_LINES_HORIZON_DAYS``."""
    return today + timedelta(days=GAME_LINES_HORIZON_DAYS)


def apply_qb_out_for_game(
    game_date: date | datetime,
    loaded_week: int,
    season: int,
    qb_out_by_team: dict[str, bool],
    *,
    home_team_name: str,
    away_team_name: str,
) -> tuple[bool, bool]:
    """Return home/away QB-out flags only when the game is in ``loaded_week``."""
    game_day = game_date.date() if isinstance(game_date, datetime) else game_date
    if get_current_nfl_week(season, today=game_day) != loaded_week:
        return False, False
    return (
        qb_out_by_team.get(home_team_name, False),
        qb_out_by_team.get(away_team_name, False),
    )


def _load_qb_out_by_team(
    db, *, season: int | None = None, week: int | None = None
) -> dict[str, bool]:
    """Map team_name → starter QB is out, from current-week ``pred_qb_predictions``."""
    season = season if season is not None else get_nfl_season()
    week = week if week is not None else get_current_nfl_week(season)
    rows = (
        db.query(QBPredictions)
        .filter(QBPredictions.season == season, QBPredictions.week == week)
        .all()
    )
    return qb_out_map_from_rows(rows)


def _load_elos(db) -> dict[str, float]:
    stored = db.query(NFLTeamElo).all()
    if stored:
        return {row.team_name: float(row.elo) for row in stored}

    actuals = (
        db.query(NFLSpreadActuals).order_by(NFLSpreadActuals.game_date.asc()).all()
    )
    if actuals:
        return load_elos_from_actuals(actuals, cfg=NFL_CONFIG)
    return {}


def _project_spread_row(
    *,
    home_team_name: str,
    away_team_name: str,
    spread_home: float | None,
    elos: dict[str, float],
    ppg_stats: dict[str, tuple[float, float]],
    home_qb_out: bool = False,
    away_qb_out: bool = False,
) -> dict:
    home_elo = elos.get(home_team_name, INITIAL_ELO)
    away_elo = elos.get(away_team_name, INITIAL_ELO)
    base_margin = _sm.expected_margin(home_elo, away_elo, cfg=NFL_CONFIG)

    home_off, home_def = team_ppg_for(home_team_name, ppg_stats)
    away_off, away_def = team_ppg_for(away_team_name, ppg_stats)
    pace_adj = _sm.pace_overlay_adjustment(
        home_off, home_def, away_off, away_def, cfg=NFL_CONFIG
    )

    qb_out_adj = qb_out_margin_adjustment(
        home_qb_out=home_qb_out, away_qb_out=away_qb_out
    )
    elo_pace_margin = base_margin + pace_adj
    projected_margin = elo_pace_margin + qb_out_adj
    home_win_prob = _sm.margin_to_win_prob(projected_margin, cfg=NFL_CONFIG)
    edge, recommendation = spread_recommendation(
        projected_margin, spread_home, cfg=NFL_CONFIG
    )

    return {
        "projected_margin": projected_margin,
        "home_win_prob": home_win_prob,
        "home_elo": home_elo,
        "away_elo": away_elo,
        "home_court_advantage": HOME_COURT_ADVANTAGE,
        "pace_adjustment": pace_adj,
        "market_spread_home": spread_home,
        "edge": edge,
        "recommendation": recommendation,
        "confidence_score": min(1.0, abs(edge) / 6.0) if edge is not None else None,
        "factors": {
            "elo_diff": home_elo - away_elo,
            "pace_adj": pace_adj,
            "elo_pace_margin": elo_pace_margin,
            "qb_out_adj": qb_out_adj,
            "method": "elo_pace",
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
        season = get_nfl_season()
        loaded_week = get_current_nfl_week(season, today=today)
        qb_out_by_team = _load_qb_out_by_team(db, season=season, week=loaded_week)

        games = (
            db.query(NFLGameLines)
            .filter(NFLGameLines.game_date >= today, NFLGameLines.game_date <= end)
            .all()
        )

        for g in games:
            home_qb_out, away_qb_out = apply_qb_out_for_game(
                g.game_date,
                loaded_week,
                season,
                qb_out_by_team,
                home_team_name=g.home_team_name,
                away_team_name=g.away_team_name,
            )
            projection = _project_spread_row(
                home_team_name=g.home_team_name,
                away_team_name=g.away_team_name,
                spread_home=g.spread_home,
                elos=elos,
                ppg_stats=ppg_stats,
                home_qb_out=home_qb_out,
                away_qb_out=away_qb_out,
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
            NFLSpreadProjections,
            upsert_rows,
            conflict_keys=["game_date", "home_team_name", "away_team_name"],
        )
        db.commit()
        return {
            "status": "ok",
            "games": len(upsert_rows),
            "projection_method": "elo_pace",
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
