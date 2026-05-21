import sys
import os
import datetime
from datetime import timedelta
from app.services.etl.mlb.pitcher_game_logs import (
    fetch_days_pitchers,
    fetch_pitcher_game_logs,
    fetch_todays_pitchers,
    calculate_metrics_actuals_v_projections,
)
from app.services.etl.mlb.regression_analysis import perform_regression_analysis
from app.models.predictions_models import (
    StrikeoutActuals,
    StrikeoutProjections,
    Pitcher,
)

from app.services.etl.mlb._db import db_session
import logging
import argparse
import traceback


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def store_projections(date):
    pitchers = db_session.query(Pitcher).all()
    if not pitchers:
        logger.warning(
            "store_projections: pred_pitcher is empty for %s — leaving "
            "existing strikeout projections in place.",
            date,
        )
        return

    # Drop rows for this date that aren't in the current pitcher slate so
    # the projections table stays in sync with today's probable starters
    # instead of accumulating stale entries from earlier (partial) runs.
    current_ids = {p.pitcher_id for p in pitchers}
    if current_ids:
        db_session.query(StrikeoutProjections).filter(
            StrikeoutProjections.date == date,
            ~StrikeoutProjections.pitcher_id.in_(current_ids),
        ).delete(synchronize_session=False)
        db_session.commit()

    for pitcher in pitchers:
        pitcher_id = pitcher.pitcher_id
        pitcher_name = pitcher.name
        innings_pitched = pitcher.projected_innings
        at_bats = pitcher.projected_at_bats
        projected_strikeouts = pitcher.projected_strikeouts
        fanduel_line = pitcher.fanduel_point
        fanduel_flag = pitcher.fanduel_flag  # 'o' for over, 'u' for under

        existing_projection = (
            db_session.query(StrikeoutProjections)
            .filter_by(date=date, pitcher_id=pitcher_id)
            .first()
        )
        if existing_projection:
            existing_projection.projected_strikeouts = projected_strikeouts
            existing_projection.projected_innings_pitched = innings_pitched
            existing_projection.projected_at_bats = at_bats
            existing_projection.fanduel_line = fanduel_line
            if fanduel_flag == "o":
                existing_projection.fanduel_over_under = "over"
            elif fanduel_flag == "u":
                existing_projection.fanduel_over_under = "under"
            else:
                existing_projection.fanduel_over_under = "push"

        else:
            new_projection = StrikeoutProjections(
                date=date,
                pitcher_id=pitcher_id,
                pitcher_name=pitcher_name,
                projected_strikeouts=projected_strikeouts,
                projected_innings_pitched=innings_pitched,
                projected_at_bats=at_bats,
                fanduel_line=fanduel_line,
                fanduel_over_under="over" if fanduel_flag == "o" else "under",
            )
            db_session.add(new_projection)
    db_session.commit()


def store_actuals(date):
    pitchers = fetch_days_pitchers(date)

    for pitcher in pitchers:
        pitcher_id = str(pitcher["pitcher_id"])
        pitcher_name = pitcher["name"]
        game_logs = fetch_pitcher_game_logs(pitcher_id)
        innings_pitched, strikeouts, at_bats, walks, hits = (
            calculate_metrics_actuals_v_projections(game_logs, date)
        )

        if innings_pitched is None or at_bats is None:
            continue

        projection = (
            db_session.query(StrikeoutProjections)
            .filter_by(date=date, pitcher_id=pitcher_id)
            .first()
        )
        if not projection:
            continue

        # Handle None fanduel_line
        if projection.fanduel_line is None:
            logger.warning(
                f"No fanduel_line available for pitcher {pitcher_name} on {date}. Skipping over/under comparison."
            )
            continue

        actual_over_under_result = (
            "over" if strikeouts > projection.fanduel_line else "under"
        )
        correct_prediction = actual_over_under_result == projection.fanduel_over_under

        existing_actual = (
            db_session.query(StrikeoutActuals)
            .filter_by(date=date, pitcher_id=pitcher_id)
            .first()
        )
        if existing_actual:
            existing_actual.actual_strikeouts = strikeouts
            existing_actual.actual_innings_pitched = innings_pitched
            existing_actual.actual_at_bats = at_bats
            existing_actual.projected_strikeouts = projection.projected_strikeouts
            existing_actual.projected_innings_pitched = (
                projection.projected_innings_pitched
            )
            existing_actual.projected_at_bats = projection.projected_at_bats
            existing_actual.correct_prediction = correct_prediction
        else:
            new_actual = StrikeoutActuals(
                date=date,
                pitcher_id=pitcher_id,
                pitcher_name=pitcher_name,
                actual_strikeouts=strikeouts,
                actual_innings_pitched=innings_pitched,
                actual_at_bats=at_bats,
                projected_strikeouts=projection.projected_strikeouts,
                projected_innings_pitched=projection.projected_innings_pitched,
                projected_at_bats=projection.projected_at_bats,
                correct_prediction=correct_prediction,
            )
            db_session.add(new_actual)
        db_session.commit()


def store_game_projections_pipeline(date):
    """Run the game-level projection pipeline and store results."""
    try:
        from app.services.etl.mlb.game_projection_pipeline import (
            run_game_projection_pipeline,
        )

        count = run_game_projection_pipeline(date)
        logger.info(f"Game projection pipeline stored {count} projections for {date}")
    except Exception as e:
        logger.error(f"Game projection pipeline failed: {e}")
        traceback.print_exc()


def store_game_actuals_pipeline(date):
    """Fetch final scores and store game actuals."""
    try:
        from app.services.etl.mlb.game_projection_pipeline import store_game_actuals

        count = store_game_actuals(date)
        logger.info(f"Stored {count} game actuals for {date}")
    except Exception as e:
        logger.error(f"Game actuals pipeline failed: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--store-actuals",
        action="store_true",
        help="Store actual game data after games have ended",
    )
    parser.add_argument(
        "--store-game-projections",
        action="store_true",
        help="Run game-level projection pipeline",
    )
    parser.add_argument(
        "--store-game-actuals",
        action="store_true",
        help="Store game-level actuals (post-game)",
    )
    parser.add_argument(
        "--all-projections",
        action="store_true",
        help="Run both K projections and game projections",
    )
    args = parser.parse_args()

    today = datetime.date.today()
    yesterday = today - timedelta(days=1)

    if args.store_actuals:
        store_actuals(yesterday)
    elif args.store_game_projections:
        store_game_projections_pipeline(today)
    elif args.store_game_actuals:
        store_game_actuals_pipeline(yesterday)
    elif args.all_projections:
        store_projections(today)
        store_game_projections_pipeline(today)
    else:
        store_projections(today)


def run_store_strikeout_projections(target_date=None) -> dict:
    from datetime import date as date_cls
    from app.services.etl.mlb._db import init_session, close_session

    init_session()
    try:
        d = target_date or date_cls.today()
        store_projections(d)
        pitchers = db_session.query(Pitcher).count()
        k_today = (
            db_session.query(StrikeoutProjections)
            .filter(StrikeoutProjections.date == d)
            .count()
        )
        if pitchers <= 0:
            return {
                "status": "error",
                "date": d.isoformat(),
                "error": "pred_pitcher empty — run mlb.strikeouts first",
                "pred_pitcher_rows": 0,
                "strikeout_projections_today": k_today,
            }
        return {
            "status": "ok",
            "date": d.isoformat(),
            "pred_pitcher_rows": pitchers,
            "strikeout_projections_today": k_today,
        }
    finally:
        close_session()


def run_store_strikeout_actuals(target_date=None) -> dict:
    from datetime import date as date_cls, timedelta
    from app.services.etl.mlb._db import init_session, close_session

    init_session()
    try:
        d = target_date or (date_cls.today() - timedelta(days=1))
        store_actuals(d)
        return {"status": "ok", "date": d.isoformat()}
    finally:
        close_session()
