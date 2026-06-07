#!/usr/bin/env python3
"""Production verification for fantasy player_analytics pipeline (FANTASY.md checklist)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any, Dict

import httpx

from app.celery_app import celery_app
from app.core.database import SessionLocal
from app.services.etl.fantasy.sync_player_analytics import (
    audit_player_analytics_mapping,
)


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
    min_analytics_rows: int,
) -> Dict[str, Any]:
    if SessionLocal is None:
        return {"ok": False, "detail": "DATABASE_URL not configured"}

    db = SessionLocal()
    try:
        mapping = await audit_player_analytics_mapping(db, season=season)
        failures = []
        if mapping["fantasy_players_mapped"] < min_mapped:
            failures.append(
                f"fantasy_players_mapped {mapping['fantasy_players_mapped']} < {min_mapped}"
            )
        if mapping["player_analytics_rows"] < min_analytics_rows:
            failures.append(
                f"player_analytics_rows {mapping['player_analytics_rows']} < {min_analytics_rows}"
            )
        return {
            "ok": not failures,
            "failures": failures,
            "mapping": mapping,
        }
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

    ok = all(
        section.get("ok") for section in report.values() if isinstance(section, dict)
    )
    report["ok"] = ok
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify fantasy ETL production readiness"
    )
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument("--min-mapped", type=int, default=1000)
    parser.add_argument("--min-analytics-rows", type=int, default=1)
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
        for key, value in report.items():
            print(f"{key}: {value}")

    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
