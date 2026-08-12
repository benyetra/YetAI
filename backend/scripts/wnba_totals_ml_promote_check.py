"""CLI: compare WNBA heuristic vs ML totals shadow and recommend promote."""

from __future__ import annotations

import json
import sys

from app.services.etl.wnba.totals_accuracy_tracker import run
from app.services.etl.wnba.totals_ml import totals_ml_enabled


def main() -> int:
    result = run()
    already_on = totals_ml_enabled()
    promote = bool(result.get("recommend_promote"))
    out = {
        **result,
        "totals_ml_currently_enabled": already_on,
        "action": (
            "already_enabled"
            if already_on
            else ("set_WNBA_TOTALS_ML_ENABLED=1" if promote else "keep_heuristic")
        ),
    }
    print(json.dumps(out, default=str, indent=2))
    if promote and not already_on:
        print(
            "\nPromote: railway variable set WNBA_TOTALS_ML_ENABLED=1 "
            "(API + celery-worker), then restart workers.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
