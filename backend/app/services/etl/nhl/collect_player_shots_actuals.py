"""NHL per-skater shots-on-goal actuals collector.

Same pattern as `collect_team_shots_actuals` but at player granularity.
Matches against `NHLPlayerShotsPredictions` by (player_id, game_date)
since player_name spellings can drift across feeds — player_id is the
stable join key on the NHL API.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sqlalchemy import and_

from app.models.predictions_models import (
    NHLPlayerShotsActuals,
    NHLPlayerShotsPredictions,
)
from app.services.etl.nhl._boxscore import (
    extract_player_shots,
    get_completed_games_for_date,
    get_game_boxscore,
    get_yesterday,
    grade_ou_pick,
)
from app.services.etl.nhl._db import close_session, init_session


def _existing_actual(db, game_id: int, player_id: int) -> bool:
    return (
        db.query(NHLPlayerShotsActuals)
        .filter(
            and_(
                NHLPlayerShotsActuals.game_id == game_id,
                NHLPlayerShotsActuals.player_id == player_id,
            )
        )
        .first()
        is not None
    )


def _find_prediction(
    db, *, player_id: int, game_date: date
) -> Optional[NHLPlayerShotsPredictions]:
    return (
        db.query(NHLPlayerShotsPredictions)
        .filter(
            and_(
                NHLPlayerShotsPredictions.player_id == player_id,
                NHLPlayerShotsPredictions.game_date == game_date,
            )
        )
        .first()
    )


def _persist_row(db, row: dict[str, Any]) -> bool:
    if _existing_actual(db, row["game_id"], row["player_id"]):
        return False
    pred = _find_prediction(db, player_id=row["player_id"], game_date=row["game_date"])
    if pred is not None:
        row["predicted_shots"] = pred.predicted_shots
        row["shots_line"] = pred.shots_line
        row["betting_recommendation"] = pred.betting_recommendation
        row["recommendation_correct"] = grade_ou_pick(
            actual=row["actual_shots"],
            line=pred.shots_line,
            recommendation=pred.betting_recommendation,
        )
    db.add(NHLPlayerShotsActuals(**row))
    return True


def update_player_shots_actuals(
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
        rows = extract_player_shots(boxscore, game_id=game_id, game_date=target)
        db = init_session()
        for row in rows:
            if _persist_row(db, row):
                inserted += 1
    if inserted:
        init_session().commit()
    return {
        "status": "ok",
        "task": "nhl_collect_player_shots_actuals",
        "date": target.isoformat(),
        "games_processed": len(games),
        "rows_inserted": inserted,
    }


def run() -> dict[str, Any]:
    init_session()
    try:
        return update_player_shots_actuals()
    finally:
        close_session()
