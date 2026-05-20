#!/usr/bin/env python3
"""Quick local smoke for mlb.strikeouts (no Railway deploy required).

Usage (from backend/):

    PYTHONPATH=. .venv/bin/python scripts/smoke_mlb_strikeouts.py
    PYTHONPATH=. .venv/bin/python scripts/smoke_mlb_strikeouts.py --with-optional
    PYTHONPATH=. .venv/bin/python scripts/smoke_mlb_strikeouts.py --live

Default: fast contract tests only (no scikit-learn / statsapi).
``--with-optional``: also run tests marked optional_deps if deps installed.
``--live``: call strikeouts.run() (needs DATABASE_URL + full requirements).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def run_pytest(include_optional: bool) -> int:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_mlb_strikeouts_local.py",
        "-q",
        "--tb=short",
    ]
    if not include_optional:
        cmd.extend(["-m", "not optional_deps"])
    print("Running:", " ".join(cmd))
    return subprocess.call(cmd, cwd=BACKEND_ROOT)


def run_live() -> int:
    print("Live run: strikeouts.run() (statsapi + DB)...")
    from app.services.etl.mlb.strikeouts import run

    result = run()
    import json

    print(json.dumps(result, indent=2, default=str))
    if result.get("status") != "ok":
        return 1
    if result.get("pred_pitcher_rows", 0) <= 0:
        print("FAIL: no pred_pitcher rows")
        return 1
    print("PASS: live strikeouts.run()")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-optional",
        action="store_true",
        help="Run sklearn-dependent tests if installed",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="After tests, run strikeouts.run() against DATABASE_URL",
    )
    args = parser.parse_args()

    code = run_pytest(include_optional=args.with_optional)
    if code != 0:
        return code
    print("PASS: strikeouts contract tests")

    if args.live:
        return run_live()
    if not args.with_optional:
        print("Tip: --with-optional for sklearn tests; --live for full DB slate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
