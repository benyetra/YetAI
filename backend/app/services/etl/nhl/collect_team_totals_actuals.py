"""NHL game-level totals (final score) actuals collector.

One row per game. Matches against `NHLTeamTotalsPredictions` by
(home_team_name, away_team_name, game_date). game_id is unique on the
actuals table so re-running is idempotent.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sqlalchemy import and_

from app.models.predictions_models import (
    NHLTeamTotalsActuals,
    NHLTeamTotalsPredictions,
)
from app.services.etl.nhl._boxscore import (
    extract_team_totals,
    get_completed_games_for_date,
    get_game_boxscore,
    get_yesterday,
    grade_ou_pick,
)
from app.services.etl.nhl._db import close_session, init_session


def _existing_actual(db, game_id: int) -> bool:
    return (
        db.query(NHLTeamTotalsActuals)
        .filter(NHLTeamTotalsActuals.game_id == game_id)
        .first()
        is not None
    )


def _find_prediction(
    db, *, home_team_name: str, away_team_name: str, game_date: date
) -> Optional[NHLTeamTotalsPredictions]:
    return (
        db.query(NHLTeamTotalsPredictions)
        .filter(
            and_(
                NHLTeamTotalsPredictions.home_team_name == home_team_name,
                NHLTeamTotalsPredictions.away_team_name == away_team_name,
                NHLTeamTotalsPredictions.game_date == game_date,
            )
        )
        .first()
    )


def _persist_row(db, row: dict[str, Any]) -> bool:
    if _existing_actual(db, row["game_id"]):
        return False
    pred = _find_prediction(
        db,
        home_team_name=row["home_team_name"],
        away_team_name=row["away_team_name"],
        game_date=row["game_date"],
    )
    if pred is not None:
        row["predicted_total_goals"] = pred.predicted_total_goals
        row["draftkings_ou_line"] = pred.draftkings_ou_line
        row["betting_recommendation"] = pred.betting_recommendation
        row["recommendation_correct"] = grade_ou_pick(
            actual=row["actual_total_goals"],
            line=pred.draftkings_ou_line,
            recommendation=pred.betting_recommendation,
        )
    db.add(NHLTeamTotalsActuals(**row))
    return True


def update_team_totals_actuals(
    target_date: Optional[date] = None,
) -> dict[str, Any]:
    target = target_date or get_yesterday()
    games = get_completed_games_for_date(target)
    inserted = 0
    for game in games:
        game_id = game.get("id")
        if game_id is None:
            continue
        boxscore = get_game_boxscore(game_id)
        if not boxscore:
            continue
        row = extract_team_totals(boxscore, game_id=game_id, game_date=target)
        if row is None:
            continue
        db = init_session()
        if _persist_row(db, row):
            inserted += 1
    if inserted:
        init_session().commit()
    return {
        "status": "ok",
        "task": "nhl_collect_team_totals_actuals",
        "date": target.isoformat(),
        "games_processed": len(games),
        "rows_inserted": inserted,
    }


def run() -> dict[str, Any]:
    init_session()
    try:
        return update_team_totals_actuals()
    finally:
        close_session()
