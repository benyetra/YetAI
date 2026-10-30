import sys
import os
from datetime import date, timedelta
from sqlalchemy import func
from app.services.etl.mlb._db import db_session
from app.services.etl.mlb.hits import (
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


def store_projections(target_date):
    hitters = (
        db_session.query(Hitter)
        .filter(func.date(Hitter.game_time) == target_date)
        .all()
    )
    homers = (
        db_session.query(Homer).filter(func.date(Homer.game_time) == target_date).all()
    )

    for hitter in hitters:
        batter_id = hitter.player_id
        batter_name = hitter.player_name
        projected_hits = hitter.hits_last_10_games

        # Store hit projections
        existing_hit_projection = (
            db_session.query(ProjectedHits)
            .filter_by(date=target_date)
            .filter_by(batter_id=batter_id)
            .first()
        )
        if existing_hit_projection:
            existing_hit_projection.projected_hits = projected_hits
        else:
            new_hit_projection = ProjectedHits(
                date=target_date,
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
            .filter_by(date=target_date)
            .filter_by(batter_id=batter_id)
            .first()
        )
        if existing_homer_projection:
            existing_homer_projection.projected_homers = projected_homers
        else:
            new_homer_projection = ProjectedHomers(
                date=target_date,
                batter_id=batter_id,
                batter_name=batter_name,
                projected_homers=projected_homers,
            )
            db_session.add(new_homer_projection)

    db_session.commit()


def _normalize_target_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _upsert_hit_actual(
    target_date: date,
    batter_id: str,
    batter_name: str,
    hits: int,
    projected_hits: int,
) -> None:
    hit_actual = (
        db_session.query(HitActuals)
        .filter_by(date=target_date, batter_id=batter_id)
        .first()
    )
    if hit_actual:
        hit_actual.actual_hits = hits
        hit_actual.projected_hits = projected_hits
        hit_actual.correct_prediction = hits >= 1
        return
    db_session.add(
        HitActuals(
            date=target_date,
            batter_id=batter_id,
            batter_name=batter_name,
            actual_hits=hits,
            projected_hits=projected_hits,
            correct_prediction=hits >= 1,
        )
    )


def _upsert_homer_actual(
    target_date: date,
    batter_id: str,
    batter_name: str,
    homers: int,
    projected_homers: int,
) -> None:
    homer_actual = (
        db_session.query(HomerActuals)
        .filter_by(date=target_date, batter_id=batter_id)
        .first()
    )
    if homer_actual:
        homer_actual.actual_homers = homers
        homer_actual.projected_homers = projected_homers
        homer_actual.correct_prediction = homers >= 1
        return
    db_session.add(
        HomerActuals(
            date=target_date,
            batter_id=batter_id,
            batter_name=batter_name,
            actual_homers=homers,
            projected_homers=projected_homers,
            correct_prediction=homers >= 1,
        )
    )


def store_actuals(date):
    """Grade yesterday's batter boards: MLB API game logs → projection + actuals tables."""
    target_date = _normalize_target_date(date)
    hit_projections = db_session.query(ProjectedHits).filter_by(date=target_date).all()
    homer_by_batter = {
        int(row.batter_id): row
        for row in db_session.query(ProjectedHomers).filter_by(date=target_date).all()
    }

    updated_hits = 0
    updated_homers = 0
    skipped_no_log = 0

    for hit_projection in hit_projections:
        batter_id_int = int(hit_projection.batter_id)
        batter_id = str(batter_id_int)
        batter_name = hit_projection.batter_name
        game_logs = get_game_log_date(batter_id, target_date)
        hits, homers = calculate_metrics_actuals_v_projections(game_logs, target_date)

        if hits is None or homers is None:
            skipped_no_log += 1
            logger.warning(
                "No game log for %s (%s) on %s",
                batter_name,
                batter_id,
                target_date,
            )
            continue

        hit_projection.actual_hits = hits
        updated_hits += 1
        _upsert_hit_actual(
            target_date,
            batter_id,
            batter_name,
            hits,
            hit_projection.projected_hits,
        )

        homer_projection = homer_by_batter.get(batter_id_int)
        if homer_projection:
            homer_projection.actual_homers = homers
            updated_homers += 1
            _upsert_homer_actual(
                target_date,
                batter_id,
                batter_name,
                homers,
                homer_projection.projected_homers,
            )

    db_session.commit()
    logger.info(
        "store_actuals %s: projected_hits=%s projected_homers=%s skipped_no_log=%s",
        target_date,
        updated_hits,
        updated_homers,
        skipped_no_log,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--store-actuals",
        action="store_true",
        help="Store actual game data after games have ended",
    )
    args = parser.parse_args()

    today = date.today()
    yesterday = date.today() - timedelta(days=1)

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
        projected_hits = db_session.query(ProjectedHits).filter_by(date=d).count()
        projected_homers = db_session.query(ProjectedHomers).filter_by(date=d).count()
        return {
            "status": "ok",
            "date": d.isoformat(),
            "projected_hits_stored": projected_hits,
            "projected_homers_stored": projected_homers,
        }
    finally:
        close_session()


def run_store_batter_actuals(target_date=None) -> dict:
    from datetime import date as date_cls, timedelta
    from app.services.etl.mlb._db import init_session, close_session

    init_session()
    try:
        d = target_date or (date_cls.today() - timedelta(days=1))
        if isinstance(d, str):
            d = date_cls.fromisoformat(d)
        before_hits = (
            db_session.query(ProjectedHits)
            .filter(
                ProjectedHits.date == d,
                ProjectedHits.actual_hits.isnot(None),
                ProjectedHits.actual_hits > 0,
            )
            .count()
        )
        store_actuals(d)
        after_hits = (
            db_session.query(ProjectedHits)
            .filter(
                ProjectedHits.date == d,
                ProjectedHits.actual_hits.isnot(None),
                ProjectedHits.actual_hits > 0,
            )
            .count()
        )
        rows = db_session.query(ProjectedHits).filter_by(date=d).count()
        return {
            "status": "ok",
            "date": d.isoformat(),
            "projected_hit_rows": rows,
            "rows_with_positive_actual_hits": after_hits,
            "delta_positive_actual_hits": after_hits - before_hits,
        }
    finally:
        close_session()
