#!/usr/bin/env python3
"""Import smoke test for ported NHL ETL modules."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

MODULES = [
    "app.services.etl.nhl._db",
    "app.services.etl.nhl.nhl_api_client",
    "app.services.etl.nhl.collect_historical_data",
    "app.services.etl.nhl.collect_goalie_actuals",
    "app.services.etl.nhl.goalie_saves_model",
    "app.services.etl.nhl.goalie_saves_ml",
    "app.services.etl.nhl.player_shots_model",
    "app.services.etl.nhl.player_shots_ml",
    "app.services.etl.nhl.team_totals_model",
    "app.services.etl.nhl.team_totals_ml",
    "app.services.etl.nhl.generate_daily_predictions",
    "app.services.etl.nhl.daily_predictions",
]


def main() -> int:
    failed = []
    for name in MODULES:
        try:
            importlib.import_module(name)
            print(f"  ok  {name}")
        except Exception as exc:
            print(f"  FAIL {name}: {exc}")
            failed.append(name)
    if failed:
        print(f"\n{len(failed)} module(s) failed")
        return 1
    print(f"\n{len(MODULES)} modules imported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
