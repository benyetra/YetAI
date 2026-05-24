#!/usr/bin/env python3
"""
End-to-end auto-pick troubleshoot against production DATABASE_URL.

1. Load auto_pick_runs row (default id=1)
2. Print projection counts for that run's UTC day
3. If counts are zero → optionally enqueue NBA + MLB pipelines (needs Redis)
4. Run AutoPickOrchestrator in-process (fixed date window) and print new run summary

Usage (CI or local):
  export DATABASE_URL=...
  export REDIS_URL=...   # optional, for --enqueue-etl
  PYTHONPATH=. python3 scripts/troubleshoot_auto_pick_workflow.py --run-id 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime

from app.core.database import SessionLocal
from app.services.auto_pick.diagnostics import get_run_diagnostics
from app.services.auto_pick.orchestrator import AutoPickOrchestrator
from app.tasks.auto_pick import _build_providers


def _print_section(title: str, payload: dict) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(payload, indent=2, default=str))


def _enqueue_etl_if_requested() -> None:
    redis_url = os.getenv("REDIS_URL") or os.getenv("CELERY_BROKER_URL")
    if not redis_url or "localhost" in redis_url:
        print(
            "SKIP enqueue-etl: REDIS_URL not set (set worker Redis URL to enqueue pipelines)",
            file=sys.stderr,
        )
        return
    from app.celery_app import celery_app

    tasks = [
        "app.tasks.etl_pipeline.run_nba_update_pipeline",
        "app.tasks.etl_pipeline.run_mlb_update_pipeline",
    ]
    ids = []
    for t in tasks:
        r = celery_app.send_task(t)
        ids.append({"task": t, "task_id": r.id})
        print(f"enqueued {t} -> {r.id}")
    print("Waiting 120s for pipelines to start (not completion)...")
    time.sleep(120)
    _print_section("enqueued_etl", {"tasks": ids})


async def _run_orchestrator_now() -> dict:
    db = SessionLocal()
    try:
        orch = AutoPickOrchestrator(
            db=db,
            providers=_build_providers(db),
            now=datetime.utcnow(),
        )
        result = await orch.run()
        return {
            "run_id": result.id,
            "status": result.status.value,
            "pick_count": result.pick_count,
        }
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-pick production troubleshoot")
    parser.add_argument("--run-id", type=int, default=1)
    parser.add_argument(
        "--enqueue-etl",
        action="store_true",
        help="Enqueue NBA+MLB orchestrators via Celery (needs REDIS_URL)",
    )
    parser.add_argument(
        "--no-rerun-orchestrator",
        action="store_true",
        help="Skip in-process orchestrator rerun (default: rerun)",
    )
    args = parser.parse_args()
    rerun_orchestrator = not args.no_rerun_orchestrator

    if not os.getenv("DATABASE_URL"):
        print("DATABASE_URL is required", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        diag = get_run_diagnostics(db, args.run_id)
        _print_section(f"auto_pick_runs id={args.run_id}", diag)

        if not diag.get("found"):
            return 1

        run_day = diag["run_day_utc"]
        counts = diag["projection_counts"]
        considered = diag["run"]["candidates_considered"]
        dropped = diag["run"].get("dropped_reasons") or {}

        print(
            f"\nSUMMARY run {args.run_id}: candidates_considered={considered}, "
            f"dropped_reasons entries={len(dropped)}"
        )

        total_proj = sum(counts.values())
        if considered == 0 and total_proj == 0:
            print(
                "\nACTION: No candidates and no projection rows for run day — "
                "ETL likely missing for this UTC date."
            )
            if args.enqueue_etl:
                _enqueue_etl_if_requested()
            else:
                print(
                    "Re-run with --enqueue-etl and REDIS_URL to queue NBA+MLB pipelines."
                )
        elif considered == 0 and total_proj > 0:
            print(
                "\nACTION: Projections exist but run had 0 candidates — "
                "likely the UTC date-window bug (fixed in PR #23). Redeploy worker/API "
                "then rerun orchestrator."
            )
        elif considered > 0 and diag["run"]["candidates_selected"] == 0:
            print(
                "\nACTION: Candidates existed but none selected — review drop_reason_summary "
                "and scoring_config.score_threshold."
            )
    finally:
        db.close()

    if rerun_orchestrator:
        print("\nRunning AutoPickOrchestrator in-process (post-fix code path)...")
        new_run = asyncio.run(_run_orchestrator_now())
        _print_section("new_orchestrator_run", new_run)
        db = SessionLocal()
        try:
            latest = get_run_diagnostics(db, new_run["run_id"])
            _print_section("new_run_diagnostics", latest)
        finally:
            db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
