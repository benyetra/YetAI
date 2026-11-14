"""NHL game-level totals (final score) actuals collector.

One row per game, keyed on game_id (unique on the actuals table). Mirrors the
prediction onto the row, matched by (game_date, home_team_id, away_team_id): the
projection writer stores both ids and names, and ids are the only unambiguous
key ("New York" is two teams). Re-collecting a date upserts, so a partial row heals.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from app.models.predictions_models import (
    NHLTeamTotalsActuals,
    NHLTeamTotalsPredictions,
)
from app.services.etl.nhl._boxscore import (
    extract_team_totals,
    get_completed_games_for_date,
    get_game_boxscore,
    grade_ou_pick,
    run_for_grading_dates,
    upsert_row,
)
from app.services.etl.nhl._db import close_session, init_session


def _find_prediction(
    db, *, home_team_id: int, away_team_id: int, game_date: date
) -> Optional[NHLTeamTotalsPredictions]:
    return (
        db.query(NHLTeamTotalsPredictions)
        .filter(
            NHLTeamTotalsPredictions.home_team_id == home_team_id,
            NHLTeamTotalsPredictions.away_team_id == away_team_id,
            NHLTeamTotalsPredictions.game_date == game_date,
        )
        .order_by(NHLTeamTotalsPredictions.id.desc())
        .first()
    )


def _persist_row(db, row: dict[str, Any]) -> str:
    pred = _find_prediction(
        db,
        home_team_id=row["home_team_id"],
        away_team_id=row["away_team_id"],
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
    return upsert_row(
        db, NHLTeamTotalsActuals, [NHLTeamTotalsActuals.game_id == row["game_id"]], row
    )


def update_team_totals_actuals(
    target_date: date, *, commit: bool = True
) -> dict[str, Any]:
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
        row = extract_team_totals(boxscore, game_id=game_id, game_date=target_date)
        if row is None:
            continue
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
            update_team_totals_actuals, "nhl_collect_team_totals_actuals"
        )
    finally:
        close_session()
