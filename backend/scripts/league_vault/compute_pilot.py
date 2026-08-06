#!/usr/bin/env python3
"""Run P2 compute + snapshot for pilot sites.

PYTHONPATH=. python3 scripts/league_vault/compute_pilot.py
PYTHONPATH=. python3 scripts/league_vault/compute_pilot.py --slug mikes-hard
PYTHONPATH=. python3 scripts/league_vault/compute_pilot.py --overrides scripts/league_vault/seed_overrides.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_DIR = ROOT / "scripts" / "league_vault_snapshots"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", action="append", dest="slugs")
    parser.add_argument("--overrides", help="JSON identity overrides file")
    parser.add_argument(
        "--out-dir",
        default=str(SNAPSHOT_DIR),
        help="Directory for snapshot JSON files",
    )
    args = parser.parse_args()

    from app.core.database import SessionLocal
    from app.models.league_vault_models import LvSite
    from app.services.league_vault.compute.records import compute_records_for_lineage
    from app.services.league_vault.compute.standings import compute_all_play_for_lineage
    from app.services.league_vault.identity.resolver import (
        apply_identity_overrides,
        load_overrides_file,
        summarize_managers,
    )
    from app.services.league_vault.publish.snapshot import (
        build_site_snapshot,
        write_snapshot_file,
    )

    if SessionLocal is None:
        raise SystemExit("DATABASE_URL not configured")

    db = SessionLocal()
    try:
        sites = db.query(LvSite).all()
        if args.slugs:
            sites = [s for s in sites if s.slug in args.slugs]
        if not sites:
            raise SystemExit("No lv_sites found — run sync_pilot.py first")

        overrides_by_slug: dict = {}
        if args.overrides:
            raw = json.loads(Path(args.overrides).read_text())
            # { "mikes-hard": [ ... ] } or flat list applied to all
            if isinstance(raw, dict) and "overrides" not in raw:
                overrides_by_slug = raw
            else:
                for s in sites:
                    overrides_by_slug[s.slug] = (
                        raw if isinstance(raw, list) else raw.get("overrides") or []
                    )

        for site in sites:
            print(f"=== {site.slug} (lineage {site.lineage_id}) ===")
            managers = summarize_managers(db, site.lineage_id)
            print(f"  managers: {len(managers)}")
            for m in managers:
                print(
                    f"    {m['display_name']!r} pid={m['platform_user_id']} "
                    f"{m['first_season']}-{m['last_season']}"
                )

            ovr = overrides_by_slug.get(site.slug) or []
            if ovr:
                if isinstance(ovr, dict) and "overrides" in ovr:
                    ovr = ovr["overrides"]
                report = apply_identity_overrides(
                    db, lineage_id=site.lineage_id, overrides=ovr
                )
                print(f"  identity overrides: {report}")

            ap = compute_all_play_for_lineage(db, site.lineage_id)
            print(f"  all-play: {ap}")
            recs = compute_records_for_lineage(db, site.lineage_id)
            print(f"  records: {len(recs)}")
            for r in recs:
                if r.record_key in (
                    "titles",
                    "biggest_blowout",
                    "highest_single_week_score",
                ):
                    print(f"    {r.record_key}={r.value} mgr={r.manager_id}")

            snap = build_site_snapshot(db, slug=site.slug)
            out = write_snapshot_file(
                snap, str(Path(args.out_dir) / f"{site.slug}.json")
            )
            print(f"  snapshot → {out}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
