"""Row counts, price share and feature NaN rates of the NBA line-residual dataset.

    DATABASE_URL=postgresql://... python scripts/nba_residual_dataset_report.py [START END]
"""

import os
import sys
import time

import pandas as pd
from sqlalchemy import create_engine

from app.services.etl.nba.residual.dataset import (
    STAT_COLUMN,
    build_rows,
    feature_columns,
    load_inputs,
)

SEASON_SPLIT = pd.Timestamp("2026-10-01")


def main(start: str = "2025-10-01", end: str = "2026-11-14") -> None:
    eng = create_engine(os.environ["DATABASE_URL"])
    t0 = time.time()
    with eng.connect() as conn:
        inputs = load_inputs(conn, start, end)
    t1 = time.time()
    print(f"load_inputs: {t1 - t0:.1f}s; box rows {len(inputs['box'])}")
    for stat in STAT_COLUMN:
        t = time.time()
        rows = build_rows(inputs, stat)
        print(f"\n== {stat}: build_rows {time.time() - t:.1f}s, {len(rows)} rows")
        season = rows["date"].map(
            lambda d: "2026-27" if d >= SEASON_SPLIT else "2025-26"
        )
        priced = rows[["over_price", "under_price"]].notna().any(axis=1)
        print(
            pd.DataFrame(
                {
                    "rows": season.value_counts(),
                    "with_price": priced.groupby(season).sum(),
                }
            )
        )
        print("line_source:", rows["line_source"].value_counts().to_dict())
        print("feature NaN rate:")
        print(rows[feature_columns()].isna().mean().round(3).to_string())


if __name__ == "__main__":
    main(*sys.argv[1:3])
