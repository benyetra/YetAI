#!/usr/bin/env python3
"""Transform copied YetiBets NFL modules for YetAI SessionLocal."""

from __future__ import annotations

import re
from pathlib import Path

NFL_ROOT = Path(__file__).resolve().parents[1] / "app" / "services" / "etl" / "nfl"
DATA_NFL = Path(__file__).resolve().parents[1] / "data" / "nfl"

MODELS = [
    "Kickers", "KickerActuals", "KickerPredictions", "FieldGoalAttempt",
    "KickerPerformanceMetrics", "WeatherImpactMetrics",
    "QBPredictions", "QBActuals",
]

REPLACEMENTS = [
    (r"from database\.models import", "from app.models.predictions_models import"),
    (r"from utilities\.config import db", "from app.services.etl.nfl._db import db_session"),
    (r"from scripts\.nfl\.", "from app.services.etl.nfl."),
    (r"from statistical_kicker_prediction import", "from app.services.etl.nfl.statistical_kicker_prediction import"),
]

STRIP = [
    re.compile(r"^import sys\n", re.M),
    re.compile(r"^import os\n", re.M),
    re.compile(r"^sys\.path\.append.*\n", re.M),
    re.compile(r"^from dotenv import load_dotenv\n", re.M),
    re.compile(r"^load_dotenv\(\)\n", re.M),
    re.compile(r"^from app import app\n", re.M),
    re.compile(r"^from app import app, db\n", re.M),
    re.compile(r"^from flask import Flask\n", re.M),
    re.compile(r"^from flask_migrate import Migrate\n", re.M),
    re.compile(r"^app = Flask\(__name__\)\n", re.M),
    re.compile(r"^app\.config\.from_object\(Config\)\n", re.M),
    re.compile(r"^db\.init_app\(app\)\n", re.M),
    re.compile(r"^migrate = Migrate\(app, db\)\n", re.M),
    re.compile(r"^with app\.app_context\(\):\n\s+db\.create_all\(\)\n", re.M),
    re.compile(r"^from utilities\.config import db, Config\n", re.M),
]


def unindent_context_blocks(s: str) -> str:
    lines = s.splitlines(keepends=True)
    out, i = [], 0
    while i < len(lines):
        if re.match(r"^(\s*)with app\.app_context\(\):\s*$", lines[i]):
            base = len(re.match(r"^(\s*)", lines[i]).group(1))
            i += 1
            while i < len(lines):
                line = lines[i]
                if line.strip() == "":
                    out.append(line)
                    i += 1
                    continue
                cur = len(line) - len(line.lstrip())
                if cur <= base and line.strip():
                    break
                out.append(line[4:] if cur >= base + 4 else line)
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "".join(out)


def transform_file(path: Path) -> None:
    text = path.read_text()
    for pat in STRIP:
        text = pat.sub("", text)
    for old, new in REPLACEMENTS:
        text = re.sub(old, new, text, flags=re.M)
    text = text.replace("db.session", "db_session")
    text = unindent_context_blocks(text)

    for m in MODELS:
        text = text.replace(f"{m}.query", f"db_session.query({m})")

    if "db_session" in text and "from app.services.etl.nfl._db import db_session" not in text:
        if "from app.models.predictions_models import" in text:
            text = text.replace(
                "from app.models.predictions_models import",
                "from app.services.etl.nfl._db import db_session\nfrom app.models.predictions_models import",
                1,
            )
        elif text.startswith("import requests"):
            text = "from app.services.etl.nfl._db import db_session\n" + text

    if path.name == "statistical_kicker_prediction.py":
        text = text.replace(
            "os.path.join(os.path.dirname(__file__), '../../data/nfl')",
            f"repr(str({DATA_NFL!r}))".replace("'", '"') if False else f'"{DATA_NFL}"',
        )
        old = "data_dir = os.path.join(os.path.dirname(__file__), '../../data/nfl')"
        text = text.replace(old, f'data_dir = "{DATA_NFL}"')

    if path.name == "qb_dynamic.py":
        text = text.replace("def main():", "def _run_qb_dynamic_core():")
        if "def run(" not in text:
            text += """

def run() -> dict:
    from app.services.etl.nfl._db import close_session, init_session
    init_session()
    try:
        _run_qb_dynamic_core()
        return {"status": "ok", "task": "nfl_qb_dynamic"}
    finally:
        close_session()
"""
        text = text.replace(
            'if __name__ == "__main__":\n    main()',
            'if __name__ == "__main__":\n    from app.services.etl.nfl._db import init_session, close_session\n    init_session()\n    try:\n        _run_qb_dynamic_core()\n    finally:\n        close_session()',
        )

    if path.name == "qb_betting.py":
        text = text.replace("def main():", "def _run_qb_betting_core():")
        if "def run(" not in text:
            text += """

def run() -> dict:
    from app.services.etl.nfl._db import close_session, init_session
    init_session()
    try:
        _run_qb_betting_core()
        return {"status": "ok", "task": "nfl_qb_betting"}
    finally:
        close_session()
"""
        text = text.replace(
            'if __name__ == "__main__":\n    main()',
            'if __name__ == "__main__":\n    from app.services.etl.nfl._db import init_session, close_session\n    init_session()\n    try:\n        _run_qb_betting_core()\n    finally:\n        close_session()',
        )

    if path.name == "kickers.py":
        text = text.replace(
            'if __name__ == "__main__":',
            "def _run_kickers_core():\n    pass  # replaced below\n\nif False and __name__ == \"__main__\":",
        )
        # Extract __main__ body into _run_kickers_core
        marker = 'if False and __name__ == "__main__":'
        if marker in text:
            idx = text.index(marker)
            main_block = text[idx:]
            body = main_block.split("\n", 1)[1] if "\n" in main_block else ""
            text = text[:idx] + "def _run_kickers_core():\n" + body
        if "def run(" not in text:
            text += """

def run() -> dict:
    from app.services.etl.nfl._db import close_session, init_session
    init_session()
    try:
        _run_kickers_core()
        return {"status": "ok", "task": "nfl_kickers"}
    finally:
        close_session()
"""

    if path.name == "collect_qb_actuals.py" and "def run(" not in text:
        text = text.replace("def main():", "def _run_qb_actuals_core():")
        text += """

def run() -> dict:
    from app.services.etl.nfl._db import close_session, init_session
    init_session()
    try:
        _run_qb_actuals_core()
        return {"status": "ok", "task": "nfl_collect_qb_actuals"}
    finally:
        close_session()
"""

    if path.name == "collect_kicker_actuals.py" and "def run(" not in text:
        if "def main(" in text:
            text = text.replace("def main():", "def _run_kicker_actuals_core():")
        text += """

def run() -> dict:
    from app.services.etl.nfl._db import close_session, init_session
    init_session()
    try:
        _run_kicker_actuals_core()
        return {"status": "ok", "task": "nfl_collect_kicker_actuals"}
    finally:
        close_session()
"""

    path.write_text(text)


def main() -> None:
    for py in sorted(NFL_ROOT.glob("*.py")):
        if py.name.startswith("_") or py.name == "nfl_common.py":
            continue
        transform_file(py)
        print(f"transformed {py.name}")


if __name__ == "__main__":
    main()
