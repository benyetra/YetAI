"""NHL team shots-on-goal actuals collector.

Reads the boxscore for each completed game on `target_date`, extracts
per-team SOG, matches against `NHLTeamShotsPredictions` for the same
(team_name, game_date), and writes (idempotently) to
`NHLTeamShotsActuals`. Mirrors `collect_goalie_actuals` for consistency.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sqlalchemy import and_

from app.models.predictions_models import (
    NHLTeamShotsActuals,
    NHLTeamShotsPredictions,
)
from app.services.etl.nhl._boxscore import (
    extract_team_shots,
    get_completed_games_for_date,
    get_game_boxscore,
    get_yesterday,
    grade_ou_pick,
)
from app.services.etl.nhl._db import close_session, init_session


def _existing_actual(db, game_id: int, team_name: str) -> bool:
    return (
        db.query(NHLTeamShotsActuals)
        .filter(
            and_(
                NHLTeamShotsActuals.game_id == game_id,
                NHLTeamShotsActuals.team_name == team_name,
            )
        )
        .first()
        is not None
    )


def _find_prediction(
    db, *, team_name: str, game_date: date
) -> Optional[NHLTeamShotsPredictions]:
    return (
        db.query(NHLTeamShotsPredictions)
        .filter(
            and_(
                NHLTeamShotsPredictions.team_name == team_name,
                NHLTeamShotsPredictions.game_date == game_date,
            )
        )
        .first()
    )


def _persist_row(db, row: dict[str, Any]) -> bool:
    """Upsert one team-shots actual. Returns True on insert, False on skip."""
    if _existing_actual(db, row["game_id"], row["team_name"]):
        return False
    pred = _find_prediction(db, team_name=row["team_name"], game_date=row["game_date"])
    if pred is not None:
        row["predicted_shots"] = pred.predicted_shots
        row["shots_line"] = pred.shots_line
        row["betting_recommendation"] = pred.betting_recommendation
        row["recommendation_correct"] = grade_ou_pick(
            actual=row["actual_shots"],
            line=pred.shots_line,
            recommendation=pred.betting_recommendation,
        )
    db.add(NHLTeamShotsActuals(**row))
    return True


def update_team_shots_actuals(target_date: Optional[date] = None) -> dict[str, Any]:
    """Pull completed games for the date and persist team-level SOG rows."""
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
        rows = extract_team_shots(boxscore, game_id=game_id, game_date=target)
        db = init_session()
        for row in rows:
            if _persist_row(db, row):
                inserted += 1
    if inserted:
        init_session().commit()
    return {
        "status": "ok",
        "task": "nhl_collect_team_shots_actuals",
        "date": target.isoformat(),
        "games_processed": len(games),
        "rows_inserted": inserted,
    }


def run() -> dict[str, Any]:
    init_session()
    try:
        return update_team_shots_actuals()
    finally:
        close_session()
