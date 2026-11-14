"""Aggregate per-stat projection accuracy into pred_prediction_accuracy."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from app.core.database import SessionLocal
from app.models.predictions_models import (
    AssistsActuals,
    AssistsProjections,
    BlocksActuals,
    BlocksProjections,
    FreeThrowActuals,
    FreeThrowPredictions,
    PointsActuals,
    PointsProjections,
    PredictionAccuracy,
    PRAActuals,
    PRAProjections,
    RecentGames,
    ReboundsActuals,
    ReboundsProjections,
    StealsActuals,
    StealsProjections,
    ActualThreePointMade,
    ThreePointProjections,
)
from app.services.etl.nba._espn import now_eastern
from app.services.etl.nba.store_actuals import opponent_matches, pra_value

logger = logging.getLogger(__name__)

db = None


def _today():
    return now_eastern().date()


STAT_CONFIGS = {
    "points": {
        "projection_model": PointsProjections,
        "actual_model": PointsActuals,
        "projection_field": "projected_points",
        "actual_field": "actual_points",
        "recent_games_field": "points",  # RecentGames column name
    },
    "assists": {
        "projection_model": AssistsProjections,
        "actual_model": AssistsActuals,
        "projection_field": "projected_assists",
        "actual_field": "actual_assists",
        "recent_games_field": "assists",
    },
    "rebounds": {
        "projection_model": ReboundsProjections,
        "actual_model": ReboundsActuals,
        "projection_field": "projected_rebounds",
        "actual_field": "actual_rebounds",
        "recent_games_field": "rebounds",
    },
    "three_pt_made": {
        "projection_model": ThreePointProjections,
        "actual_model": ActualThreePointMade,
        "projection_field": "projected_three_pt_made",
        "actual_field": "actual_three_pt_made",
        "recent_games_field": "three_pt_made",
    },
    "blocks": {
        "projection_model": BlocksProjections,
        "actual_model": BlocksActuals,
        "projection_field": "projected_blocks",
        "actual_field": "actual_blocks",
        "recent_games_field": "blocks",
    },
    "steals": {
        "projection_model": StealsProjections,
        "actual_model": StealsActuals,
        "projection_field": "projected_steals",
        "actual_field": "actual_steals",
        "recent_games_field": "steals",
    },
    "free_throws": {
        "projection_model": FreeThrowPredictions,
        "actual_model": FreeThrowActuals,
        "projection_field": "predicted_free_throws",
        "actual_field": "actual_free_throws",
        "recent_games_field": "free_throws_made",
    },
    "pra": {
        "projection_model": PRAProjections,
        "actual_model": PRAActuals,
        "projection_field": "projected_pra",
        "actual_field": "actual_pra",
        "recent_games_field": None,  # PRA is computed: points + rebounds + assists
        "compute_from_fields": ["points", "rebounds", "assists"],  # Fields to sum
    },
}


def calculate_accuracy_for_date(target_date, dry_run=False):
    """
    Calculate accuracy for all projections on a given date.

    RecentGames (box scores) is the only source of actual values; a row with
    no matching box value is deleted.

    Args:
        target_date: Date to calculate accuracy for
        dry_run: count what would change without writing

    Returns counts: created, updated, deleted, unchanged.
    """
    logger.info(f"Calculating accuracy for {target_date}")

    records_created = 0
    records_updated = 0
    records_skipped = 0
    records_deleted = 0
    records_unchanged = 0

    for stat_type, config in STAT_CONFIGS.items():
        try:
            projection_model = config["projection_model"]
            actual_model = config["actual_model"]
            proj_field = config["projection_field"]
            actual_field = config["actual_field"]
            recent_games_field = config.get("recent_games_field")

            # Skip stat types without projection models (like steals)
            if projection_model is None:
                continue

            # Get projections for the date
            projections = db.query(projection_model).filter_by(date=target_date).all()

            if not projections:
                logger.debug(f"No {stat_type} projections found for {target_date}")
                continue

            logger.info(f"Processing {len(projections)} {stat_type} projections")

            for proj in projections:
                try:
                    player_id = proj.player_id
                    projected_value = getattr(proj, proj_field)

                    if projected_value is None:
                        records_skipped += 1
                        continue

                    # Box score only: the actuals tables are derived from it, so
                    # falling back to them could only return a stale grade.
                    actual_value = None
                    minutes_played = None
                    recent_game = (
                        db.query(RecentGames)
                        .filter_by(player_id=player_id, game_date=target_date)
                        .first()
                    )

                    if recent_game and opponent_matches(proj, recent_game):
                        minutes_played = recent_game.minutes
                        if recent_games_field:
                            actual_value = getattr(
                                recent_game, recent_games_field, None
                            )
                        elif config.get("compute_from_fields"):
                            actual_value = pra_value(recent_game)

                    existing = (
                        db.query(PredictionAccuracy)
                        .filter_by(
                            player_id=player_id,
                            game_date=target_date,
                            stat_type=stat_type,
                        )
                        .first()
                    )

                    # No box value (not played, re-dated away, wrong opponent):
                    # an old grade must not outlive it.
                    if actual_value is None:
                        if existing:
                            if not dry_run:
                                db.delete(existing)
                                db.commit()
                            records_deleted += 1
                        records_skipped += 1
                        continue

                    if dry_run:
                        if existing is None:
                            records_created += 1
                        elif (existing.projected_value, existing.actual_value) != (
                            float(projected_value),
                            float(actual_value),
                        ):
                            records_updated += 1
                        else:
                            records_unchanged += 1
                        continue

                    if existing:
                        existing.projected_value = float(projected_value)
                        existing.actual_value = float(actual_value)
                        existing.minutes_played = minutes_played
                        existing.calculate_error()
                        existing.updated_at = datetime.utcnow()
                        records_updated += 1
                    else:
                        accuracy_record = PredictionAccuracy(
                            player_id=player_id,
                            player_name=proj.player_name,
                            game_date=target_date,
                            stat_type=stat_type,
                            projected_value=float(projected_value),
                            actual_value=float(actual_value),
                            minutes_played=minutes_played,
                            opponent_team_id=getattr(proj, "opponent_team_id", None),
                            is_home_game=getattr(proj, "is_home_game", None),
                        )
                        accuracy_record.calculate_error()
                        db.add(accuracy_record)
                        records_created += 1

                    db.commit()

                except Exception as e:
                    logger.error(
                        f"Error processing {stat_type} for player {proj.player_id}: {e}"
                    )
                    db.rollback()
                    continue

        except Exception as e:
            logger.error(f"Error processing {stat_type}: {e}")
            continue

    logger.info(
        f"Created {records_created} records, updated {records_updated} records, "
        f"deleted {records_deleted}, skipped {records_skipped}"
    )
    return {
        "created": records_created,
        "updated": records_updated,
        "deleted": records_deleted,
        "unchanged": records_unchanged,
    }


def generate_accuracy_report(days_back=7):
    """
    Generate accuracy report for recent predictions.

    Args:
        days_back: Number of days to analyze

    Returns:
        Dict with accuracy metrics by stat type
    """
    cutoff_date = _today() - timedelta(days=days_back)

    report = {
        "period": f"Last {days_back} days",
        "generated_at": datetime.now().isoformat(),
        "stats": {},
    }

    # Only report on stat types that have projection models
    reportable_stats = [
        k for k, v in STAT_CONFIGS.items() if v.get("projection_model") is not None
    ]

    for stat_type in reportable_stats:
        try:
            # Get records with actual values
            records = (
                db.query(PredictionAccuracy)
                .filter(
                    PredictionAccuracy.stat_type == stat_type,
                    PredictionAccuracy.game_date >= cutoff_date,
                    PredictionAccuracy.actual_value.isnot(None),
                )
                .all()
            )

            if not records:
                report["stats"][stat_type] = {
                    "message": "No data",
                    "total_predictions": 0,
                }
                continue

            # Calculate metrics
            total_predictions = len(records)
            errors = [r.error for r in records if r.error is not None]
            abs_errors = [
                r.absolute_error for r in records if r.absolute_error is not None
            ]
            pct_errors = [
                r.percentage_error for r in records if r.percentage_error is not None
            ]

            if not errors:
                report["stats"][stat_type] = {
                    "message": "No error data",
                    "total_predictions": total_predictions,
                }
                continue

            mae = sum(abs_errors) / len(abs_errors)  # Mean Absolute Error
            mse = sum(e**2 for e in errors) / len(errors)  # Mean Squared Error
            rmse = mse**0.5  # Root Mean Squared Error

            # Calculate bias (positive = over-predicting, negative = under-predicting)
            bias = sum(errors) / len(errors)

            # Calculate percentage within thresholds (stat-appropriate)
            within_1 = sum(1 for e in abs_errors if e <= 1.0) / len(abs_errors) * 100
            within_2 = sum(1 for e in abs_errors if e <= 2.0) / len(abs_errors) * 100
            within_3 = sum(1 for e in abs_errors if e <= 3.0) / len(abs_errors) * 100
            within_5 = sum(1 for e in abs_errors if e <= 5.0) / len(abs_errors) * 100

            # Average percentage error
            mape = sum(pct_errors) / len(pct_errors) if pct_errors else 0

            # Calculate over/under accuracy (how often we predicted the right direction vs line)
            # This is useful for betting accuracy
            correct_direction = 0
            direction_total = 0
            for r in records:
                if r.projected_value is not None and r.actual_value is not None:
                    # Determine if prediction was correct direction
                    # For this we'd need the betting line, which we may not have stored
                    direction_total += 1

            report["stats"][stat_type] = {
                "total_predictions": total_predictions,
                "mae": round(mae, 2),
                "rmse": round(rmse, 2),
                "bias": round(bias, 2),
                "mape": round(mape, 1),
                "within_1": round(within_1, 1),
                "within_2": round(within_2, 1),
                "within_3": round(within_3, 1),
                "within_5": round(within_5, 1),
            }

        except Exception as e:
            logger.error(f"Error generating report for {stat_type}: {e}")
            report["stats"][stat_type] = {"error": str(e)}

    return report


def print_accuracy_report(report):
    """Pretty print the accuracy report."""
    print("\n" + "=" * 80)
    print(f"PREDICTION ACCURACY REPORT - {report['period']}")
    print("=" * 80)

    for stat_type, metrics in report["stats"].items():
        print(f"\n{stat_type.upper()}")
        print("-" * 40)

        if "message" in metrics:
            print(f"  {metrics['message']}")
            if "total_predictions" in metrics:
                print(f"  Total Predictions: {metrics['total_predictions']}")
            continue

        if "error" in metrics:
            print(f"  Error: {metrics['error']}")
            continue

        print(f"  Total Predictions: {metrics['total_predictions']}")
        print(f"  Mean Absolute Error (MAE): {metrics['mae']}")
        print(f"  Root Mean Squared Error (RMSE): {metrics['rmse']}")
        bias_direction = (
            "over-predicting" if metrics["bias"] > 0 else "under-predicting"
        )
        print(f"  Bias: {metrics['bias']} ({bias_direction})")
        print(f"  Mean Absolute Percentage Error: {metrics['mape']}%")
        print(f"  Within 1 of actual: {metrics['within_1']}%")
        print(f"  Within 2 of actual: {metrics['within_2']}%")
        print(f"  Within 3 of actual: {metrics['within_3']}%")
        print(f"  Within 5 of actual: {metrics['within_5']}%")

    print("\n" + "=" * 80)


REPORT_DAYS = 7
DEFAULT_BACKFILL_DAYS = 2


def _backfill_days() -> int:
    """Days re-graded each night (yesterday included). Grading costs about five
    queries per date, so the default is short. ``NBA_ACCURACY_BACKFILL_DAYS``
    widens it for a catch-up; else ``NBA_GRADING_LOOKBACK_DAYS`` (shared with the
    other NBA graders) applies."""
    for name in ("NBA_ACCURACY_BACKFILL_DAYS", "NBA_GRADING_LOOKBACK_DAYS"):
        raw = os.getenv(name, "").strip()
        if not raw:
            continue
        try:
            return max(1, int(raw))
        except ValueError:
            logger.warning("Bad %s=%r; ignoring", name, raw)
    return DEFAULT_BACKFILL_DAYS


def run(backfill_days: int | None = None) -> dict:
    global db
    if backfill_days is None:
        backfill_days = _backfill_days()
    db = SessionLocal()
    try:
        yesterday = _today() - timedelta(days=1)
        calculate_accuracy_for_date(yesterday)
        for days_ago in range(2, backfill_days + 1):
            calculate_accuracy_for_date(_today() - timedelta(days=days_ago))
        # The report reads stored rows, so it keeps its own 7-day window.
        report = generate_accuracy_report(days_back=max(REPORT_DAYS, backfill_days))
        return {"status": "ok", "yesterday": yesterday.isoformat(), "report": report}
    finally:
        db.close()
