#!/usr/bin/env python3
"""Tune NFL kicker ML blend weight from FG history CSV (offline).

Writes recommended weight into models/nfl/kicker_blend_tune.json and prints
the env var to set in Railway.

With DATABASE_URL, also reports prod ``pred_kicker_actuals`` FG MAE
(projected vs made) so blend quality is measurable after collect/backfill.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

_MODELS_DIR = Path(__file__).resolve().parents[1] / "models" / "nfl"


def _prod_kicker_fg_mae() -> dict[str, Any] | None:
    if not os.getenv("DATABASE_URL", "").strip():
        return None
    try:
        import numpy as np
        from app.core.database import SessionLocal
        from app.models.predictions_models import KickerActuals

        session = SessionLocal()
        try:
            rows = session.query(KickerActuals).all()
        finally:
            session.close()
        if not rows:
            return {"n": 0, "kicker_mae": None, "note": "pred_kicker_actuals empty"}
        errs = [
            abs(float(r.projected_field_goals) - float(r.actual_field_goals_made))
            for r in rows
            if r.projected_field_goals is not None
            and r.actual_field_goals_made is not None
        ]
        if not errs:
            return {"n": 0, "kicker_mae": None}
        return {
            "n": len(errs),
            "kicker_mae": round(float(np.mean(errs)), 3),
            "source": "pred_kicker_actuals.projected_field_goals",
        }
    except Exception as exc:
        return {"error": str(exc)}


def main() -> int:
    from app.services.etl.nfl.kicker_volume import (
        walk_forward_default_blend_from_fg_csv,
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Write JSON artifact")
    args = parser.parse_args()

    weight = walk_forward_default_blend_from_fg_csv()
    payload: dict[str, Any] = {
        "tuned_at": datetime.utcnow().isoformat(),
        "NFL_KICKER_BLEND_TUNED_WEIGHT": round(float(weight), 3),
        "source": "field_goal_data.csv walk-forward proxy",
        "note": (
            "Prefer re-tuning from prod statistical_fgs/ml_fgs/actual_fg_made "
            "rows when available; this CSV proxy is a bootstrap default."
        ),
    }
    prod = _prod_kicker_fg_mae()
    if prod is not None:
        payload["prod_fg_mae"] = prod
    print(json.dumps(payload, indent=2))
    if args.write:
        _MODELS_DIR.mkdir(parents=True, exist_ok=True)
        path = _MODELS_DIR / "kicker_blend_tune.json"
        path.write_text(json.dumps(payload, indent=2))
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
