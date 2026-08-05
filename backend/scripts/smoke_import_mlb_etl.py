#!/usr/bin/env python3
"""Import MLB ETL modules (Railway layout check).

Usage (from backend/ with project venv active):

    PYTHONPATH=. python scripts/smoke_import_mlb_etl.py
    PYTHONPATH=. python scripts/smoke_import_mlb_etl.py --all
    PYTHONPATH=. python scripts/smoke_import_mlb_etl.py --verbose

Default mode imports **pipeline-critical** modules (Celery daily path + direct deps).
Use ``--all`` for every ``.py`` under ``app/services/etl/mlb/`` except known side-effect
or broken-layout modules (``backtest.py`` shadows ``backtest/`` package in YetiBets).

Exits 0 if all targeted imports succeed, 1 otherwise.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import traceback
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MLB_ROOT = BACKEND_ROOT / "app" / "services" / "etl" / "mlb"
PACKAGE_PREFIX = "app.services.etl.mlb"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Celery run_mlb_update_pipeline / store_actuals dependency chain
PIPELINE_MODULES = [
    "app.services.etl.mlb._db",
    "app.services.etl.mlb._mlb_utils",
    "app.services.etl.mlb._venues",
    "app.services.etl.mlb.strikeouts",
    "app.services.etl.mlb.hits",
    "app.services.etl.mlb.daily_projection_update",
    "app.services.etl.mlb.game_projection_pipeline",
    "app.services.etl.mlb.daily_batter_projection",
    "app.services.etl.mlb.weather",
    "app.services.etl.mlb.blowouts",
    "app.services.etl.mlb.bullpen_fatigue",
    "app.services.etl.mlb.regression_analysis",
    "app.services.etl.mlb.mlb_matchup_analysis",
    "app.services.etl.mlb.mlb_pitcher_analysis",
    "app.services.etl.mlb.mlb_batter_analysis",
    "app.services.etl.mlb.lineup_utils",
    "app.services.etl.mlb.profiles.lineup_runs",
    "app.services.etl.mlb.profiles.archetypes",
    "app.services.etl.mlb.profiles.pitcher_archetypes",
    "app.services.etl.mlb.profiles.pa_sim_pilot",
    "app.services.etl.mlb.profiles.monitoring",
    "app.services.etl.mlb.pitcher_game_logs",
    "app.services.etl.mlb.game_model",
    "app.services.etl.mlb.injury_tracker",
    "app.services.etl.mlb.pipeline",
]

# Not import-safe in isolation (side effects, or backtest.py vs backtest/ package)
SKIP_ALL_MODE = {
    f"{PACKAGE_PREFIX}.backtest",
    f"{PACKAGE_PREFIX}.verify_backtest_prd",
}

BACKTEST_MODULES = [
    "app.services.etl.mlb.backtest",
    "app.services.etl.mlb.backtest.cli",
    "app.services.etl.mlb.backtest.cache",
    "app.services.etl.mlb.backtest.sampler",
    "app.services.etl.mlb.backtest.actuals_fetcher",
    "app.services.etl.mlb.backtest.data_builder",
    "app.services.etl.mlb.backtest.model_runner",
    "app.services.etl.mlb.backtest.scorer",
    "app.services.etl.mlb.backtest.report",
    "app.services.etl.mlb.backtest.persistence",
]


def discover_all_modules() -> list[str]:
    names: list[str] = []
    for path in sorted(MLB_ROOT.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        rel = path.relative_to(MLB_ROOT).with_suffix("")
        name = f"{PACKAGE_PREFIX}.{'.'.join(rel.parts)}"
        if name in SKIP_ALL_MODE:
            continue
        names.append(name)
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Import every module (not just pipeline-critical)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--backtest",
        action="store_true",
        help="Import backtest package modules only",
    )
    args = parser.parse_args()

    if args.backtest:
        modules = list(BACKTEST_MODULES)
        mode = "backtest package"
    elif args.all:
        modules = discover_all_modules()
        mode = "all (excl. skip list)"
    else:
        modules = list(PIPELINE_MODULES)
        mode = "pipeline-critical"
    print(f"MLB ETL import smoke test — {mode} ({len(modules)} modules)")
    print(f"  root: {MLB_ROOT}")
    print()

    failed: list[tuple[str, str]] = []
    for name in modules:
        try:
            importlib.import_module(name)
            if args.verbose:
                print(f"  OK  {name}")
        except Exception as exc:
            failed.append((name, f"{type(exc).__name__}: {exc}"))
            print(f"  FAIL {name}")
            if args.verbose:
                traceback.print_exc()

    print()
    if failed:
        print(f"FAILED: {len(failed)} / {len(modules)} modules could not import")
        for name, err in failed:
            print(f"  - {name}: {err}")
        print()
        print(
            "Tip: activate backend/.venv and install requirements.txt (pandas, statsapi, etc.)"
        )
        return 1

    print(f"PASS: all {len(modules)} targeted MLB ETL modules imported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
