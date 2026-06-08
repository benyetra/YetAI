#!/usr/bin/env python3
"""Production verification for fantasy player_analytics pipeline (FANTASY.md checklist).

Exit codes:
  0 — all critical checks passed (warnings may still be printed)
  1 — one or more critical checks failed

Critical failures (non-zero exit):
  - Celery beat entry ``fantasy-player-analytics-weekly`` missing or misconfigured
  - ``player_analytics`` has zero rows for the requested season (when DB checks run)
  - Optional API smoke: any of accounts / leagues / start-sit returned non-200

Warnings (exit 0 unless paired with a critical failure):
  - ``player_analytics_rows`` below season threshold (default 1000 for season >= 2024)
  - ``fantasy_players_mapped`` below ``--min-mapped`` (GSIS mapping coverage)

Flags:
  --season              NFL season to audit (default 2025)
  --min-mapped          Minimum GSIS-mapped fantasy_players (default 1000)
  --min-analytics-rows  Override season default row threshold (default: 1000 if season >= 2024 else 1)
  --skip-db             Skip DATABASE_URL checks (beat schedule only)
  --api-url / --token   Optional authenticated API smoke against legacy fantasy routes
  --week                NFL week for start/sit smoke (default 1)
  --json                Emit full report as JSON
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any, Dict, List, Optional

import httpx

from app.celery_app import celery_app
from app.core.database import SessionLocal
from app.services.etl.fantasy.sync_player_analytics import (
    audit_player_analytics_mapping,
)


def min_analytics_rows_for_season(season: int) -> int:
    """Return the expected minimum player_analytics row count for a season."""
    return 1000 if season >= 2024 else 1


def format_mapping_summary(mapping: Dict[str, Any]) -> str:
    """One-line audit summary for operator logs."""
    return (
        f"season={mapping.get('season')} "
        f"player_analytics_rows={mapping.get('player_analytics_rows')} "
        f"fantasy_players_mapped={mapping.get('fantasy_players_mapped')} "
        f"skip_rate_pct={mapping.get('skip_rate_pct')}"
    )


def evaluate_db_health(
    mapping: Dict[str, Any],
    *,
    season: int,
    min_mapped: int,
    min_analytics_rows: Optional[int] = None,
) -> Dict[str, Any]:
    """Classify mapping audit results into critical failures vs warnings."""
    threshold = (
        min_analytics_rows
        if min_analytics_rows is not None
        else min_analytics_rows_for_season(season)
    )
    rows = int(mapping.get("player_analytics_rows") or 0)
    mapped = int(mapping.get("fantasy_players_mapped") or 0)

    failures: List[str] = []
    warnings: List[str] = []

    if rows == 0:
        failures.append(f"player_analytics empty for season {season}")
    elif rows < threshold:
        warnings.append(
            f"player_analytics_rows {rows} < {threshold} (expected for season {season})"
        )

    if mapped < min_mapped:
        warnings.append(
            f"fantasy_players_mapped {mapped} < {min_mapped} (low GSIS mapping coverage)"
        )

    return {
        "ok": not failures,
        "failures": failures,
        "warnings": warnings,
        "mapping_summary": format_mapping_summary(mapping),
        "mapping": mapping,
        "thresholds": {
            "min_analytics_rows": threshold,
            "min_mapped": min_mapped,
        },
    }


def _beat_schedule_ok() -> Dict[str, Any]:
    schedule = celery_app.conf.beat_schedule or {}
    entry = schedule.get("fantasy-player-analytics-weekly")
    if entry is None:
        return {
            "ok": False,
            "detail": "fantasy-player-analytics-weekly missing from beat",
        }
    task = entry.get("task", "")
    expected = "app.tasks.etl_pipeline.fantasy.sync_player_analytics"
    if task != expected:
        return {"ok": False, "detail": f"beat task is {task!r}, expected {expected!r}"}
    return {
        "ok": True,
        "task": task,
        "schedule": str(entry.get("schedule")),
    }


async def _db_checks(
    season: int,
    *,
    min_mapped: int,
    min_analytics_rows: Optional[int],
) -> Dict[str, Any]:
    if SessionLocal is None:
        return {"ok": False, "detail": "DATABASE_URL not configured", "failures": []}

    db = SessionLocal()
    try:
        mapping = await audit_player_analytics_mapping(db, season=season)
        return evaluate_db_health(
            mapping,
            season=season,
            min_mapped=min_mapped,
            min_analytics_rows=min_analytics_rows,
        )
    finally:
        db.close()


async def _api_smoke(
    api_url: str,
    token: str,
    *,
    week: int,
) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    base = api_url.rstrip("/")
    async with httpx.AsyncClient(timeout=30.0) as client:
        accounts = await client.get(f"{base}/api/fantasy/accounts", headers=headers)
        leagues = await client.get(f"{base}/api/fantasy/leagues", headers=headers)
        start_sit = await client.get(
            f"{base}/api/fantasy/recommendations/start-sit/{week}",
            headers=headers,
        )

    failures = []
    for label, response in (
        ("accounts", accounts),
        ("leagues", leagues),
        ("start_sit", start_sit),
    ):
        if response.status_code != 200:
            failures.append(f"{label} HTTP {response.status_code}")

    start_sit_body = start_sit.json() if start_sit.status_code == 200 else {}
    rec_count = len(start_sit_body.get("recommendations") or [])

    return {
        "ok": not failures,
        "failures": failures,
        "accounts_status": accounts.status_code,
        "leagues_status": leagues.status_code,
        "start_sit_status": start_sit.status_code,
        "start_sit_recommendations": rec_count,
    }


async def run_checks(args: argparse.Namespace) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "beat_schedule": _beat_schedule_ok(),
    }

    if not args.skip_db:
        report["database"] = await _db_checks(
            args.season,
            min_mapped=args.min_mapped,
            min_analytics_rows=args.min_analytics_rows,
        )

    if args.api_url and args.token:
        report["api_smoke"] = await _api_smoke(
            args.api_url,
            args.token,
            week=args.week,
        )

    warnings: List[str] = []
    for section in report.values():
        if isinstance(section, dict):
            warnings.extend(section.get("warnings") or [])

    ok = all(
        section.get("ok") for section in report.values() if isinstance(section, dict)
    )
    report["ok"] = ok
    report["warnings"] = warnings
    return report


def _print_report(report: Dict[str, Any]) -> None:
    for key, value in report.items():
        if key == "warnings":
            continue
        print(f"{key}: {value}")

    db = report.get("database")
    if isinstance(db, dict) and db.get("mapping_summary"):
        print(f"mapping_audit: {db['mapping_summary']}")

    warnings = report.get("warnings") or []
    for warning in warnings:
        print(f"WARNING: {warning}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify fantasy ETL production readiness"
    )
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument("--min-mapped", type=int, default=1000)
    parser.add_argument(
        "--min-analytics-rows",
        type=int,
        default=None,
        help=("Minimum player_analytics rows (default: 1000 for season>=2024, else 1)"),
    )
    parser.add_argument("--skip-db", action="store_true")
    parser.add_argument("--api-url", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--week", type=int, default=1)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = asyncio.run(run_checks(args))

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_report(report)

    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
