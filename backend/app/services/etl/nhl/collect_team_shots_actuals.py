"""NHL team shots-on-goal actuals collector.

No projection writer exists for `NHLTeamShotsPredictions`, so this is not in
NHL_PHASES and nothing grades from it; kept so the actuals can be backfilled if a
writer is ever added. Matches predictions by (team_id, game_date); upserts.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from app.models.predictions_models import (
    NHLTeamShotsActuals,
    NHLTeamShotsPredictions,
)
from app.services.etl.nhl._boxscore import (
    extract_team_shots,
    get_completed_games_for_date,
    get_game_boxscore,
    grade_ou_pick,
    run_for_grading_dates,
    upsert_row,
)
from app.services.etl.nhl._db import close_session, init_session


def _find_prediction(
    db, *, team_id: int, game_date: date
) -> Optional[NHLTeamShotsPredictions]:
    return (
        db.query(NHLTeamShotsPredictions)
        .filter(
            NHLTeamShotsPredictions.team_id == team_id,
            NHLTeamShotsPredictions.game_date == game_date,
        )
        .order_by(NHLTeamShotsPredictions.id.desc())
        .first()
    )


def _persist_row(db, row: dict[str, Any]) -> str:
    pred = _find_prediction(db, team_id=row["team_id"], game_date=row["game_date"])
    if pred is not None:
        row["predicted_shots"] = pred.predicted_shots
        row["shots_line"] = pred.shots_line
        row["betting_recommendation"] = pred.betting_recommendation
        row["recommendation_correct"] = grade_ou_pick(
            actual=row["actual_shots"],
            line=pred.shots_line,
            recommendation=pred.betting_recommendation,
        )
    return upsert_row(
        db,
        NHLTeamShotsActuals,
        [
            NHLTeamShotsActuals.game_id == row["game_id"],
            NHLTeamShotsActuals.team_id == row["team_id"],
        ],
        row,
    )


def update_team_shots_actuals(
    target_date: date, *, commit: bool = True
) -> dict[str, Any]:
    """Pull completed games for the date and persist team-level SOG rows."""
    games = get_completed_games_for_date(target_date)
    db = init_session()
    counts = {"inserted": 0, "updated": 0, "unchanged": 0}
    for game in games:
        game_id = game.get("id")
        if game_id is None:
            continue
        boxscore = get_game_boxscore(game_id)
        if not boxscore:
            continue
        for row in extract_team_shots(boxscore, game_id=game_id, game_date=target_date):
            counts[_persist_row(db, row)] += 1
    db.commit() if commit else db.rollback()
    return {
        "date": target_date.isoformat(),
        "games_processed": len(games),
        "rows_inserted": counts["inserted"],
        "rows_updated": counts["updated"],
    }


def run() -> dict[str, Any]:
    init_session()
    try:
        return run_for_grading_dates(
            update_team_shots_actuals, "nhl_collect_team_shots_actuals"
        )
    finally:
        close_session()
