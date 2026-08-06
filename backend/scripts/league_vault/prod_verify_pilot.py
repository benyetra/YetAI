#!/usr/bin/env python3
"""Verify League Vault pilot readiness before sharing links.

Checks DB sites + optional live API. Exit 0 only if all critical checks pass.

  export DATABASE_URL=...
  PYTHONPATH=. python3 scripts/league_vault/prod_verify_pilot.py
  PYTHONPATH=. python3 scripts/league_vault/prod_verify_pilot.py \\
    --api-url https://api.yetai.app --slugs mikes-hard,league-838295
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import httpx

EXPECTED = (
    "mikes-hard",
    "league-838295",
)


def check_db(slugs: list[str]) -> dict[str, Any]:
    from app.core.database import SessionLocal
    from app.models.league_vault_models import (
        LvManager,
        LvRecord,
        LvSeason,
        LvSite,
        LvTeam,
    )

    if SessionLocal is None:
        return {"ok": False, "failures": ["DATABASE_URL / SessionLocal unavailable"]}

    failures: list[str] = []
    warnings: list[str] = []
    sites_out: list[dict[str, Any]] = []

    db = SessionLocal()
    try:
        for slug in slugs:
            site = db.query(LvSite).filter_by(slug=slug).first()
            if not site:
                failures.append(f"{slug}: site missing")
                continue
            if not site.is_public:
                failures.append(f"{slug}: is_public=false (vault API will 404)")
            seasons = (
                db.query(LvSeason)
                .filter_by(lineage_id=site.lineage_id)
                .order_by(LvSeason.season)
                .all()
            )
            if not seasons:
                failures.append(f"{slug}: no seasons ingested")
            managers = db.query(LvManager).filter_by(lineage_id=site.lineage_id).count()
            records = db.query(LvRecord).filter_by(lineage_id=site.lineage_id).count()
            if records == 0:
                warnings.append(
                    f"{slug}: no lv_records — run compute_pilot.py before sharing"
                )
            champs_ok = all(s.champion_manager_id for s in seasons if s.season < 2026)
            if seasons and not champs_ok:
                warnings.append(
                    f"{slug}: some completed seasons missing champion_manager_id"
                )
            team_counts = []
            for s in seasons:
                team_counts.append(
                    {
                        "season": s.season,
                        "teams": db.query(LvTeam).filter_by(season_id=s.id).count(),
                        "champion_id": s.champion_manager_id,
                    }
                )
            sites_out.append(
                {
                    "slug": slug,
                    "display_name": site.display_name,
                    "is_public": site.is_public,
                    "first_season": site.first_season,
                    "latest_season": site.latest_season,
                    "managers": managers,
                    "records": records,
                    "seasons": team_counts,
                }
            )
    finally:
        db.close()

    return {
        "ok": not failures,
        "failures": failures,
        "warnings": warnings,
        "sites": sites_out,
    }


def check_api(api_url: str, slugs: list[str]) -> dict[str, Any]:
    failures: list[str] = []
    results: list[dict[str, Any]] = []
    base = api_url.rstrip("/")
    with httpx.Client(timeout=30.0) as client:
        for slug in slugs:
            meta = client.get(f"{base}/api/vault/{slug}/meta")
            full = client.get(f"{base}/api/vault/{slug}")
            stats = client.get(f"{base}/api/vault/{slug}/stats")
            if meta.status_code != 200:
                failures.append(f"{slug}: meta HTTP {meta.status_code}")
            if full.status_code != 200:
                failures.append(f"{slug}: snapshot HTTP {full.status_code}")
            else:
                body = full.json()
                if "platform_user_id" in str(body):
                    failures.append(f"{slug}: snapshot leaked platform_user_id")
                if not body.get("seasons"):
                    failures.append(f"{slug}: snapshot has no seasons")
                draft_picks = 0
                identified = 0
                for season in body.get("seasons") or []:
                    for draft in season.get("drafts") or []:
                        for pick in draft.get("picks") or []:
                            draft_picks += 1
                            if pick.get("team_id") or pick.get("player_id"):
                                identified += 1
                if draft_picks and identified == 0:
                    failures.append(
                        f"{slug}: draft picks present but team_id/player_id all null"
                    )
            results.append(
                {
                    "slug": slug,
                    "meta": meta.status_code,
                    "snapshot": full.status_code,
                    "stats": stats.status_code,
                }
            )
    return {"ok": not failures, "failures": failures, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--slugs",
        default=",".join(EXPECTED),
        help="Comma-separated vault slugs",
    )
    parser.add_argument("--api-url", help="Optional live API base URL")
    parser.add_argument("--skip-db", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    slugs = [s.strip() for s in args.slugs.split(",") if s.strip()]

    report: dict[str, Any] = {"slugs": slugs}
    failures: list[str] = []

    if not args.skip_db:
        db_report = check_db(slugs)
        report["db"] = db_report
        failures.extend(db_report.get("failures") or [])
        for w in db_report.get("warnings") or []:
            print(f"WARN  {w}", file=sys.stderr)

    if args.api_url:
        api_report = check_api(args.api_url, slugs)
        report["api"] = api_report
        failures.extend(api_report.get("failures") or [])

    report["ok"] = not failures
    report["failures"] = failures

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("=== League Vault pilot verify ===")
        if report.get("db"):
            for site in report["db"].get("sites") or []:
                print(
                    f"  {site['slug']}: public={site['is_public']} "
                    f"seasons={len(site['seasons'])} managers={site['managers']} "
                    f"records={site['records']}"
                )
        if report.get("api"):
            for row in report["api"].get("results") or []:
                print(
                    f"  API {row['slug']}: meta={row['meta']} "
                    f"snapshot={row['snapshot']} stats={row['stats']}"
                )
        if failures:
            print("FAILED:")
            for f in failures:
                print(f"  - {f}")
        else:
            print("OK — ready to share (pending DNS/OG smoke).")

    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
