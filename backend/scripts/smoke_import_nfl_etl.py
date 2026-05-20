#!/usr/bin/env python3
"""Import smoke test for ported NFL ETL modules."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

MODULES = [
    "app.services.etl.nfl._db",
    "app.services.etl.nfl.nfl_common",
    "app.services.etl.nfl.collect_qb_actuals",
    "app.services.etl.nfl.collect_kicker_actuals",
    "app.services.etl.nfl.qb_dynamic",
    "app.services.etl.nfl.qb_betting",
    "app.services.etl.nfl.qb_weekly",
    "app.services.etl.nfl.kickers",
    "app.services.etl.nfl.kicker_prediction",
    "app.services.etl.nfl.statistical_kicker_prediction",
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
