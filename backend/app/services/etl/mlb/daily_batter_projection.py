import sys
import os
from datetime import date, timedelta
from app.services.etl.mlb._db import db_session
from app.services.etl.mlb.hits import (
    fetch_days_hitters,
    get_game_log_date,
    get_game_logs,
    calculate_metrics_actuals_v_projections,
)

from app.models.predictions_models import (
    HitActuals,
    HomerActuals,
    ProjectedHits,
    ProjectedHomers,
    Hitter,
    Homer,
)
import logging
import argparse


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def store_projections(date):
    hitters = db_session.query(Hitter).all()
    homers = db_session.query(Homer).all()

    for hitter in hitters:
        batter_id = hitter.player_id
        batter_name = hitter.player_name
        projected_hits = hitter.hits_last_10_games

        # Store hit projections
        existing_hit_projection = (
            db_session.query(ProjectedHits)
            .filter_by(date=date)
            .filter_by(batter_id=batter_id)
            .first()
        )
        if existing_hit_projection:
            existing_hit_projection.projected_hits = projected_hits
        else:
            new_hit_projection = ProjectedHits(
                date=date,
                batter_id=batter_id,
                batter_name=batter_name,
                projected_hits=projected_hits,
            )
            db_session.add(new_hit_projection)

    for homer in homers:
        batter_id = homer.player_id
        batter_name = homer.player_name
        projected_homers = homer.home_runs_last_10_games

        # Store homer projections
        existing_homer_projection = (
            db_session.query(ProjectedHomers)
            .filter_by(date=date)
            .filter_by(batter_id=batter_id)
            .first()
        )
        if existing_homer_projection:
            existing_homer_projection.projected_homers = projected_homers
        else:
            new_homer_projection = ProjectedHomers(
                date=date,
                batter_id=batter_id,
                batter_name=batter_name,
                projected_homers=projected_homers,
            )
            db_session.add(new_homer_projection)

    db_session.commit()


def store_actuals(date):
    hitters = fetch_days_hitters(date)

    for hitter in hitters:
        batter_id = str(hitter["id"])
        batter_name = hitter["fullName"]
        game_logs = get_game_log_date(batter_id, date)
        hits, homers = calculate_metrics_actuals_v_projections(game_logs, date)

        if hits is None or homers is None:
            continue

        # Fetch existing projections
        hit_projection = (
            db_session.query(ProjectedHits)
            .filter_by(date=date, batter_id=batter_id)
            .first()
        )
        homer_projection = (
            db_session.query(ProjectedHomers)
            .filter_by(date=date, batter_id=batter_id)
            .first()
        )
        if not hit_projection or not homer_projection:
            continue

        # Store actual hit results in HitActuals
        hit_actual = (
            db_session.query(HitActuals)
            .filter_by(date=date, batter_id=batter_id)
            .first()
        )
        if hit_actual:
            hit_actual.actual_hits = hits
            hit_actual.projected_hits = (
                hit_projection.projected_hits
            )  # Set the projected_hits from the projection
            hit_actual.correct_prediction = (
                hits >= 1
            )  # Determine if the prediction was correct
        else:
            new_hit_actual = HitActuals(
                date=date,
                batter_id=batter_id,
                batter_name=batter_name,
                actual_hits=hits,
                projected_hits=hit_projection.projected_hits,  # Set the projected_hits
                correct_prediction=hits >= 1,  # Determine if the prediction was correct
            )
            db_session.add(new_hit_actual)

        # Store actual homer results in HomerActuals
        homer_actual = (
            db_session.query(HomerActuals)
            .filter_by(date=date, batter_id=batter_id)
            .first()
        )
        if homer_actual:
            homer_actual.actual_homers = homers
            homer_actual.projected_homers = (
                homer_projection.projected_homers
            )  # Set the projected_homers from the projection
            homer_actual.correct_prediction = (
                homers >= 1
            )  # Determine if the prediction was correct
        else:
            new_homer_actual = HomerActuals(
                date=date,
                batter_id=batter_id,
                batter_name=batter_name,
                actual_homers=homers,
                projected_homers=homer_projection.projected_homers,  # Set the projected_homers
                correct_prediction=homers
                >= 1,  # Determine if the prediction was correct
            )
            db_session.add(new_homer_actual)

        db_session.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--store-actuals",
        action="store_true",
        help="Store actual game data after games have ended",
    )
    args = parser.parse_args()

    # Use the correct date format: 'YYYY-MM-DD' for processing, 'MM/DD/YYYY' for API requests
    today = date.today().strftime("%Y-%m-%d")
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

    if args.store_actuals:
        store_actuals(yesterday)
    else:
        store_projections(today)


def run_projections(target_date=None) -> dict:
    from datetime import date as date_cls
    from app.services.etl.mlb._db import init_session, close_session

    init_session()
    try:
        d = target_date or date_cls.today()
        store_projections(d)
        return {"status": "ok", "date": d.isoformat()}
    finally:
        close_session()


def run_store_batter_actuals(target_date=None) -> dict:
    from datetime import date as date_cls, timedelta
    from app.services.etl.mlb._db import init_session, close_session

    init_session()
    try:
        d = target_date or (date_cls.today() - timedelta(days=1))
        store_actuals(d)
        return {"status": "ok", "date": d.isoformat()}
    finally:
        close_session()
