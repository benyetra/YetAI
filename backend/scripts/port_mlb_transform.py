#!/usr/bin/env python3
"""One-time transform: adapt copied YetiBets MLB modules for YetAI SessionLocal."""

from __future__ import annotations

import re
from pathlib import Path

MLB_ROOT = Path(__file__).resolve().parents[1] / "app" / "services" / "etl" / "mlb"

REPLACEMENTS = [
    (r"from database\.models import", "from app.models.predictions_models import"),
    (r"from database\.database import db_session", "from app.services.etl.mlb._db import db_session"),
    (r"from utilities\.utilities_functions import \*", "from app.services.etl.mlb._mlb_utils import *"),
    (r"from utilities\.utilities_functions import", "from app.services.etl.mlb._mlb_utils import"),
    (r"from utilities\.config import db, Config", ""),
    (r"from utilities\.config import Config, db", ""),
    (r"from utilities\.config import Config", ""),
    (r"from utilities\.data\.stadium_zipcode import", "from app.services.etl.mlb.data.stadium_zipcode import"),
    (r"from utilities\.data\.special_characters_mapping import", "from app.services.etl.mlb.data.special_characters_mapping import"),
    (r"from utilities\.venues import venues", "from app.services.etl.mlb._venues import venues"),
    (r"from scripts\.mlb\.", "from app.services.etl.mlb."),
    (r"import scripts\.mlb\.", "import app.services.etl.mlb."),
    (r"from scripts\.mlb import", "from app.services.etl.mlb import"),
    (r"^from regression_analysis import", "from app.services.etl.mlb.regression_analysis import"),
    (r"^from mlb_matchup_analysis import", "from app.services.etl.mlb.mlb_matchup_analysis import"),
    (r"^from pitcher_game_logs import", "from app.services.etl.mlb.pitcher_game_logs import"),
    (r"datetime\.timedelta", "timedelta"),
]

STRIP_PATTERNS = [
    re.compile(r"^sys\.path\.append.*\n", re.M),
    re.compile(r"^from dotenv import load_dotenv\n", re.M),
    re.compile(r"^load_dotenv\(\)\n", re.M),
    re.compile(r"^from flask import.*\n", re.M),
    re.compile(r"^from flask_migrate import.*\n", re.M),
    re.compile(r"^app = Flask\(__name__\)\n", re.M),
    re.compile(r"^app\.config\.from_object\(Config\)\n", re.M),
    re.compile(r"^db\.init_app\(app\)\n", re.M),
    re.compile(r"^migrate = Migrate\(app, db\)\n", re.M),
    re.compile(r"^with app\.app_context\(\):\n\s+db\.create_all\(\)\n", re.M),
    re.compile(
        r"^@app\.teardown_appcontext\ndef shutdown_session.*?\n\n",
        re.M | re.S,
    ),
]

HITS_FIX = [
    (
        "db.session.execute(text('DROP TABLE IF EXISTS hitter'))",
        "db_session.query(Hitter).delete()",
    ),
    (
        "db.session.execute(text('DROP TABLE IF EXISTS homer'))",
        "db_session.query(Homer).delete()",
    ),
    ("db.create_all()", "# tables managed by Alembic"),
    ("db.session.commit()", "db_session.commit()"),
]


def transform_file(path: Path) -> bool:
    text = path.read_text()
    original = text
    for pat in STRIP_PATTERNS:
        text = pat.sub("", text)
    for old, new in REPLACEMENTS:
        text = re.sub(old, new, text, flags=re.M)
    if path.name == "hits.py":
        for old, new in HITS_FIX:
            text = text.replace(old, new)
        if "from app.models.predictions_models import" in text and "Hitter" not in text.split("import")[1][:200]:
            text = text.replace(
                "from app.models.predictions_models import Homer",
                "from app.models.predictions_models import Hitter, Homer",
            )
    if path.name == "strikeouts.py" and "def run(" not in text:
        text += """

def run() -> dict:
    \"\"\"Rebuild pred_pitcher (strikeout board) for today's slate.\"\"\"
    from app.services.etl.mlb._db import init_session, close_session
    init_session()
    try:
        fetch_and_update_app_data()
        return {"status": "ok", "task": "strikeouts"}
    finally:
        close_session()
"""
    if path.name == "hits.py" and "def run(" not in text:
        text = text.replace(
            "def main():",
            "def _run_hits_core():",
        )
        text += """

def run() -> dict:
    \"\"\"Rebuild pred_hitter and pred_homer boards.\"\"\"
    from app.services.etl.mlb._db import init_session, close_session
    init_session()
    try:
        _run_hits_core()
        return {"status": "ok", "task": "hits"}
    finally:
        close_session()
"""
    if path.name == "game_projection_pipeline.py" and "def run_game_projections(" not in text:
        text += """

def run_game_projections(target_date=None) -> dict:
    from app.services.etl.mlb._db import init_session, close_session
    from datetime import date as date_cls
    init_session()
    try:
        td = target_date or date_cls.today()
        count = run_game_projection_pipeline(td)
        return {"status": "ok", "date": td.isoformat(), "games_stored": count}
    finally:
        close_session()


def run_store_game_actuals(target_date=None) -> dict:
    from app.services.etl.mlb._db import init_session, close_session
    from datetime import date as date_cls, timedelta
    init_session()
    try:
        td = target_date or (date_cls.today() - timedelta(days=1))
        count = store_game_actuals(td)
        return {"status": "ok", "date": td.isoformat(), "actuals_stored": count}
    finally:
        close_session()
"""
    if path.name == "daily_projection_update.py":
        text += """

def run_store_strikeout_projections(target_date=None) -> dict:
    from datetime import date as date_cls
    from app.services.etl.mlb._db import init_session, close_session
    init_session()
    try:
        d = target_date or date_cls.today()
        store_projections(d)
        return {"status": "ok", "date": d.isoformat()}
    finally:
        close_session()


def run_store_strikeout_actuals(target_date=None) -> dict:
    from datetime import date as date_cls, timedelta
    from app.services.etl.mlb._db import init_session, close_session
    init_session()
    try:
        d = target_date or (date_cls.today() - timedelta(days=1))
        store_actuals(d)
        return {"status": "ok", "date": d.isoformat()}
    finally:
        close_session()
"""
    if path.name == "daily_batter_projection.py" and "def run_projections(" not in text:
        text += """

def run_projections(target_date=None) -> dict:
    from datetime import date as date_cls
    from app.services.etl.mlb._db import init_session, close_session
    init_session()
    try:
        d = target_date or date_cls.today()
        store_batter_projections(d)
        return {"status": "ok", "date": d.isoformat()}
    finally:
        close_session()


def run_store_batter_actuals(target_date=None) -> dict:
    from datetime import date as date_cls, timedelta
    from app.services.etl.mlb._db import init_session, close_session
    init_session()
    try:
        d = target_date or (date_cls.today() - timedelta(days=1))
        store_batter_actuals(d)
        return {"status": "ok", "date": d.isoformat()}
    finally:
        close_session()
"""
    if path.name == "weather.py" and "\ndef run(" not in text:
        text += """

def run() -> dict:
    from app.services.etl.mlb._db import init_session, close_session
    init_session()
    try:
        refresh_weather()
        return {"status": "ok", "task": "weather"}
    finally:
        close_session()
"""
    if path.name == "blowouts.py" and "\ndef run(" not in text:
        text += """

def run() -> dict:
    from app.services.etl.mlb._db import init_session, close_session
    init_session()
    try:
        main()
        return {"status": "ok", "task": "blowouts"}
    finally:
        close_session()
"""
    # dingerParlay predict_today
    if path.name == "predict_today.py" and path.parent.name == "dingerParlay":
        text = text.replace(
            "from utilities.config import Config, db",
            "from app.services.etl.mlb._db import db_session",
        )
        text += """

def run(model_path: str | None = None, daily_csv: str | None = None) -> dict:
    import argparse
    from app.services.etl.mlb._db import init_session, close_session
    init_session()
    try:
        # Delegate to CLI main with defaults if present
        import sys
        argv = ["predict_today.py"]
        if model_path:
            argv += ["--model", model_path]
        if daily_csv:
            argv += ["--daily-csv", daily_csv]
        old = sys.argv
        sys.argv = argv
        try:
            if __name__ == "__main__":
                pass
            main()
        finally:
            sys.argv = old
        return {"status": "ok", "task": "hr_predictions"}
    finally:
        close_session()
"""
    if text != original:
        path.write_text(text)
        return True
    return False


def main() -> None:
    changed = 0
    for path in sorted(MLB_ROOT.rglob("*.py")):
        if path.name == "port_mlb_transform.py":
            continue
        if transform_file(path):
            changed += 1
            print("updated", path.relative_to(MLB_ROOT.parent.parent.parent))
    print(f"done, {changed} files updated")


if __name__ == "__main__":
    main()
