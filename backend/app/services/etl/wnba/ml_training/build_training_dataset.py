"""WNBA training dataset builder — thin wrapper over shared ML package."""

from __future__ import annotations

from datetime import date

import pandas as pd

from app.services.etl.wnba.ml_training.config import WNBA_ML_CONFIG
from app.services.ml import build_training_dataset as _shared


def build(
    stat_col: str, season_start: date, season_end: date
) -> tuple[pd.DataFrame, pd.Series]:
    return _shared.build(WNBA_ML_CONFIG, stat_col, season_start, season_end)
