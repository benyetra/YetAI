#!/usr/bin/env python3
"""Tune NFL kicker ML blend weight from FG history CSV (offline).

Writes recommended weight into models/nfl/kicker_blend_tune.json and prints
the env var to set in Railway.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

_MODELS_DIR = Path(__file__).resolve().parents[1] / "models" / "nfl"


def main() -> int:
    from app.services.etl.nfl.kicker_volume import (
        walk_forward_default_blend_from_fg_csv,
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Write JSON artifact")
    args = parser.parse_args()

    weight = walk_forward_default_blend_from_fg_csv()
    payload = {
        "tuned_at": datetime.utcnow().isoformat(),
        "NFL_KICKER_BLEND_TUNED_WEIGHT": round(float(weight), 3),
        "source": "field_goal_data.csv walk-forward proxy",
        "note": (
            "Prefer re-tuning from prod statistical_fgs/ml_fgs/actual_fg_made "
            "rows when available; this CSV proxy is a bootstrap default."
        ),
    }
    print(json.dumps(payload, indent=2))
    if args.write:
        _MODELS_DIR.mkdir(parents=True, exist_ok=True)
        path = _MODELS_DIR / "kicker_blend_tune.json"
        path.write_text(json.dumps(payload, indent=2))
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
