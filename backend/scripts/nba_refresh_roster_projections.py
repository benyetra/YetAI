"""Refresh pred_team_roster, then re-project today's NBA totals and spreads.

Same steps and code as the daily pipeline's roster refresh and its totals /
spread projectors, run from a GitHub Actions runner against production. Use it
when the worker can't be redeployed (Railway builds paused) or to refresh the
slate after a roster fix without re-running the whole pipeline: the full
pipeline re-runs the worker's own roster update first.

    PYTHONPATH=. python3 scripts/nba_refresh_roster_projections.py
"""

from __future__ import annotations

import json
import sys

from app.services.etl.nba import spread_projector, totals_projector, update_team_roster


def main() -> int:
    steps = (
        ("update_team_roster", update_team_roster.run),
        ("totals_projector", totals_projector.run),
        ("spread_projector", spread_projector.run),
    )
    for name, run in steps:
        result = run()
        print(f"{name}: {json.dumps(result, default=str)}")
        if isinstance(result, dict) and result.get("status") == "error":
            print(f"ERROR: {name} failed; later steps skipped.")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
