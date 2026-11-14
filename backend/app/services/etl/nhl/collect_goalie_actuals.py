#!/usr/bin/env python3
"""
NHL Goalie Actuals Collection Script
Collects actual goalie save performance data and compares with predictions.

Predictions are matched on (goalie_id, game_date): the boxscore spells goalies
"I. Sorokin" while the projection writer stores "Ilya Sorokin". Re-collecting a
date upserts, so a partial row heals.
"""

from datetime import datetime, date
from typing import Any, Optional

from app.models.predictions_models import NHLGoaliePredictions, NHLGoalieActuals
from app.services.etl.nhl._boxscore import (
    _team_name,
    get_completed_games_for_date,
    get_game_boxscore,
    grade_ou_pick,
    run_for_grading_dates,
    upsert_row,
)
from app.services.etl.nhl._db import close_session, db_session, init_session


def extract_goalie_stats(game_data, game_id, game_date):
    """Extract goalie statistics from game data"""
    goalie_stats = []

    if not game_data or "playerByGameStats" not in game_data:
        return goalie_stats

    teams = {
        "awayTeam": game_data.get("awayTeam", {}),
        "homeTeam": game_data.get("homeTeam", {}),
    }
    opponents = {"awayTeam": "homeTeam", "homeTeam": "awayTeam"}

    for side, team in teams.items():
        side_stats = game_data["playerByGameStats"].get(side) or {}
        for goalie in side_stats.get("goalies", []):
            goalie_stats.append(
                {
                    "game_id": game_id,
                    "game_date": game_date,
                    "goalie_id": goalie.get("playerId"),
                    "goalie_name": goalie.get("name", {}).get("default", ""),
                    "team_name": _team_name(team),
                    "opponent_team_name": _team_name(teams[opponents[side]]),
                    "actual_saves": goalie.get("saves", 0),
                    "actual_shots_against": goalie.get("shotsAgainst", 0),
                    "actual_save_pct": goalie.get("savePctg", 0.0),
                    "actual_goals_against": goalie.get("goalsAgainst", 0),
                    "actual_toi": goalie.get("toi", "0:00"),
                    "decision": goalie.get("decision", ""),
                }
            )

    return goalie_stats


def _played_minutes(toi: str) -> Optional[int]:
    parts = (toi or "").split(":")
    return int(parts[0]) if len(parts) == 2 and parts[0].isdigit() else None


def build_actual_row(stats: dict[str, Any], prediction) -> dict[str, Any]:
    """Actuals row from boxscore stats plus the mirrored prediction (if any)."""
    row = {
        k: stats[k]
        for k in (
            "game_id",
            "game_date",
            "goalie_id",
            "goalie_name",
            "team_name",
            "opponent_team_name",
            "actual_saves",
            "actual_shots_against",
            "actual_save_pct",
            "actual_goals_against",
            "actual_toi",
            "decision",
        )
    }
    if prediction is None:
        return row

    predicted_saves = prediction.predicted_saves
    actual_saves = stats["actual_saves"]
    row["predicted_saves"] = predicted_saves
    row["predicted_shots_against"] = prediction.predicted_shots_against
    row["prediction_error"] = abs(predicted_saves - actual_saves)
    # Within 2 saves is considered accurate
    row["correct_prediction"] = abs(predicted_saves - actual_saves) <= 2

    if prediction.saves_line:
        row["sportsbook"] = prediction.sportsbook
        row["saves_line"] = prediction.saves_line
        row["over_odds"] = prediction.over_odds
        row["under_odds"] = prediction.under_odds
        row["betting_recommendation"] = prediction.betting_recommendation
        row["edge_category"] = prediction.edge_category
        row["edge_saves"] = prediction.edge_saves
        # Shared grading: PASS and a push (actual == line) are None, not a loss.
        row["recommendation_correct"] = grade_ou_pick(
            actual=actual_saves,
            line=prediction.saves_line,
            recommendation=prediction.betting_recommendation,
        )
    return row


def _find_prediction(goalie_id, game_date):
    return (
        db_session.query(NHLGoaliePredictions)
        .filter(
            NHLGoaliePredictions.goalie_id == goalie_id,
            NHLGoaliePredictions.game_date == game_date,
        )
        .order_by(NHLGoaliePredictions.id.desc())
        .first()
    )


def match_with_predictions(goalie_stats, *, commit: bool = True) -> dict[str, int]:
    """Match actual results with our predictions and upsert them."""
    counts = {"inserted": 0, "updated": 0, "unchanged": 0}

    for stats in goalie_stats:
        goalie_name = stats["goalie_name"]
        game_date = stats["game_date"]
        goalie_id = stats["goalie_id"]

        # Only process goalies who played significant time (> 10 minutes)
        minutes = _played_minutes(stats["actual_toi"])
        if minutes is not None and minutes < 10:
            print(f"⏭️  Skipping {goalie_name} - only played {stats['actual_toi']}")
            continue

        prediction = _find_prediction(goalie_id, game_date)
        if prediction is None:
            print(f"⚠️  No prediction found for {goalie_name} on {game_date}")
        row = build_actual_row(stats, prediction)
        counts[
            upsert_row(
                db_session,
                NHLGoalieActuals,
                [
                    NHLGoalieActuals.game_id == stats["game_id"],
                    NHLGoalieActuals.goalie_id == goalie_id,
                ],
                row,
            )
        ] += 1

    db_session.commit() if commit else db_session.rollback()
    print(f"📊 Goalie actuals: {counts}")
    return counts


def update_goalie_actuals(target_date: date, *, commit: bool = True) -> dict[str, Any]:
    """Collect and upsert goalie actuals for one date (Eastern game day)."""
    games = get_completed_games_for_date(target_date)
    all_goalie_stats = []
    for game in games:
        game_id = game["id"]
        game_data = get_game_boxscore(game_id)
        if game_data:
            all_goalie_stats.extend(
                extract_goalie_stats(game_data, game_id, target_date)
            )

    counts = (
        match_with_predictions(all_goalie_stats, commit=commit)
        if all_goalie_stats
        else {}
    )
    return {
        "date": target_date.isoformat(),
        "games_processed": len(games),
        "rows_inserted": counts.get("inserted", 0),
        "rows_updated": counts.get("updated", 0),
    }


def run() -> dict:
    init_session()
    try:
        return run_for_grading_dates(
            update_goalie_actuals, "nhl_collect_goalie_actuals"
        )
    finally:
        close_session()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Collect NHL goalie actual results")
    parser.add_argument("--date", type=str, help="Date to process (YYYY-MM-DD)")

    args = parser.parse_args()

    init_session()
    try:
        if args.date:
            print(
                update_goalie_actuals(datetime.strptime(args.date, "%Y-%m-%d").date())
            )
        else:
            print(run())
    finally:
        close_session()
