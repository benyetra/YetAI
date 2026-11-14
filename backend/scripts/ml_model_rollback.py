"""Roll a live ML model back to an archived copy in s3://yetibets.

Every champion-gated upload (app/services/ml/model_store.gated_upload) first
copies the live model, its metadata and its manifest to
``<model dir>/archive/<UTC stamp>/``. This restores one of those sets.

    # list archive stamps for a model
    python scripts/ml_model_rollback.py --key nba/ml_models/xgb_points.pkl --list
    # show what would be restored (default: dry run)
    python scripts/ml_model_rollback.py --key nba/ml_models/xgb_points.pkl --stamp 20261113T110000
    # do it (the current live copy is archived first, so this is undoable)
    python scripts/ml_model_rollback.py --key nba/ml_models/xgb_points.pkl --stamp 20261113T110000 --apply

Running workers pick the restored model up within ML_MODEL_REFRESH_SECONDS
(default 3600); restart the worker to force it. ``--extra`` names additional
files stored next to the model (default: ``<model>_metadata.json``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ml import model_store  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--key", required=True, help="model key, e.g. nba/ml_models/xgb_points.pkl")
    ap.add_argument("--list", action="store_true", help="list archive stamps")
    ap.add_argument("--stamp", help="archive stamp to restore")
    ap.add_argument("--extra", action="append", help="extra basename stored with the model")
    ap.add_argument("--apply", action="store_true", help="perform the rollback (default: dry run)")
    args = ap.parse_args(argv)

    if args.list:
        print("\n".join(model_store.list_archive_stamps(args.key)))
        return 0
    if not args.stamp:
        ap.error("--stamp is required unless --list")
    extras = tuple(args.extra or [f"{args.key.rsplit('/', 1)[-1].rsplit('.', 1)[0]}_metadata.json"])
    out = model_store.rollback(
        args.key, args.stamp, extra_basenames=extras, dry_run=not args.apply
    )
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
