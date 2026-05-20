#!/usr/bin/env python3
"""One-time transform: adapt copied YetiBets NHL modules for YetAI SessionLocal."""

from __future__ import annotations

import re
from pathlib import Path

NHL_ROOT = Path(__file__).resolve().parents[1] / "app" / "services" / "etl" / "nhl"

REPLACEMENTS = [
    (r"from database\.models import", "from app.models.predictions_models import"),
    (
        r"from database\.database import db_session",
        "from app.services.etl.nhl._db import db_session",
    ),
    (
        r"from utilities\.config import db",
        "from app.services.etl.nhl._db import db_session",
    ),
    (
        r"from utilities\.config import db, Config",
        "from app.services.etl.nhl._db import db_session",
    ),
    (r"from scripts\.nhl\.", "from app.services.etl.nhl."),
    (r"import scripts\.nhl\.", "import app.services.etl.nhl."),
    (r"from scripts\.nhl import", "from app.services.etl.nhl import"),
]

STRIP_PATTERNS = [
    re.compile(r"^sys\.path\.append.*\n", re.M),
    re.compile(r"^from dotenv import load_dotenv\n", re.M),
    re.compile(r"^load_dotenv\(\)\n", re.M),
    re.compile(r"^from app import app\n", re.M),
    re.compile(r"^from app import app, db\n", re.M),
    re.compile(r"^from utilities\.config import db\n", re.M),
]

DB_SESSION_FIXES = [
    ("db.session.", "db_session."),
    ("with app.app_context():", ""),
    ("    with app.app_context():", ""),
]


def transform_file(path: Path) -> bool:
    text = path.read_text()
    original = text
    for pat in STRIP_PATTERNS:
        text = pat.sub("", text)
    for old, new in REPLACEMENTS:
        text = re.sub(old, new, text, flags=re.M)
    for old, new in DB_SESSION_FIXES:
        text = text.replace(old, new)

    # Dedent one level where we stripped `with app.app_context():`
    if path.name in (
        "collect_historical_data.py",
        "daily_predictions.py",
        "collect_goalie_actuals.py",
    ):
        lines = text.splitlines(keepends=True)
        out = []
        for line in lines:
            if line.startswith("        ") and not line.startswith("            "):
                # was double-indented under app context
                pass
            out.append(line)
        text = "".join(out)

    if path.name == "collect_historical_data.py" and "def run_ingest(" not in text:
        text += """

def run_ingest(season: int = 20252026) -> dict:
    \"\"\"Populate teams, ingest recent games, recalc goalie/team tables.\"\"\"
    from app.services.etl.nhl._db import close_session, init_session

    init_session()
    try:
        populate_teams()
        collect_game_data(season=season, max_games_per_team=20)
        calculate_goalie_stats()
        calculate_team_stats()
        update_special_teams_stats(season)
        update_realtime_stats(season)
        calculate_shot_quality_metrics(season, sample_games=20)
        collect_season_player_stats(season)
        collect_team_offensive_stats(season)
        return {"status": "ok", "task": "nhl_ingest", "season": season}
    finally:
        close_session()


def run_update_daily_stats(season: int = 20252026) -> dict:
    \"\"\"Daily stats refresh (PP/PK, shot quality, player/team offense).\"\"\"
    from app.services.etl.nhl._db import close_session, init_session

    init_session()
    try:
        update_daily_stats(season=season)
        return {"status": "ok", "task": "nhl_update_daily_stats", "season": season}
    finally:
        close_session()
"""

    if path.name == "collect_goalie_actuals.py" and "def run(" not in text:
        text = text.replace(
            "def update_goalie_actuals():", "def _update_goalie_actuals_core():"
        )
        text += """

def run() -> dict:
    from app.services.etl.nhl._db import close_session, init_session

    init_session()
    try:
        count = _update_goalie_actuals_core()
        return {"status": "ok", "task": "nhl_collect_goalie_actuals", "actuals": count}
    finally:
        close_session()
"""
        if "def main(" in text:
            text = text.replace("def main():", "def _cli_main():")

    if path.name == "daily_predictions.py" and "def run(" not in text:
        text = text.replace("def main():", "def _run_daily_core():")
        text += """

def run() -> dict:
    \"\"\"Full NHL daily automation: stats, goalie/player/totals preds, actuals.\"\"\"
    from app.services.etl.nhl._db import close_session, init_session

    init_session()
    try:
        _run_daily_core()
        return {"status": "ok", "task": "nhl_daily_predictions"}
    finally:
        close_session()
"""

    if path != original or text != original:
        path.write_text(text)
        return True
    return False


def main() -> None:
    if not NHL_ROOT.is_dir():
        raise SystemExit(f"Missing {NHL_ROOT}")
    changed = 0
    for py in sorted(NHL_ROOT.glob("*.py")):
        if py.name.startswith("_"):
            continue
        if transform_file(py):
            changed += 1
            print(f"transformed {py.name}")
    # Remove duplicate copy
    dup = NHL_ROOT / "automated_daily_predictions.py"
    if dup.exists():
        dup.unlink()
        print("removed automated_daily_predictions.py (use daily_predictions.py)")
    print(f"done ({changed} files)")


if __name__ == "__main__":
    main()
