"""Build QB passing yards training set from pred_qb_actuals + tier replay."""

from __future__ import annotations

from datetime import date

import pandas as pd

from app.services.etl.nfl.qb_dynamic import predict_qb_passing_yards
from app.services.etl.nfl.qb_passing_yards_ml import (
    build_features_from_tier_prediction,
    feature_names,
)


def build(
    season_start: date,
    season_end: date,
    *,
    session=None,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Rows from ``pred_qb_actuals`` with tier features replayed per QB/week.

    Requires DATABASE_URL when ``session`` is None.
    """
    from app.models.predictions_models import QBActuals

    if session is None:
        from app.core.database import SessionLocal

        session = SessionLocal()
        own = True
    else:
        own = False

    try:
        rows = (
            session.query(QBActuals)
            .filter(
                QBActuals.game_date >= season_start,
                QBActuals.game_date <= season_end,
            )
            .all()
        )
        if not rows:
            return pd.DataFrame(columns=feature_names()), pd.Series(dtype=float)

        records: list[dict[str, float]] = []
        targets: list[float] = []
        for row in rows:
            tier_pred = predict_qb_passing_yards(
                row.qb_player_name,
                int(row.season),
                int(row.week),
                is_backup=False,
            )
            feats = build_features_from_tier_prediction(
                tier_pred,
                season=int(row.season),
                week=int(row.week),
            )
            records.append(feats)
            targets.append(float(row.actual_passing_yards))

        return pd.DataFrame(records), pd.Series(targets, name="actual_passing_yards")
    finally:
        if own:
            session.close()
