#!/usr/bin/env python3
"""Verify the MLB strikeout classifier unpickles in this environment.

The S3 artifact was trained with ``scikit-learn==1.5.0`` (see ``requirements.txt``).
Unpickling with a newer sklearn (e.g. 1.9) often fails with ``No module named '_loss'``.

Run with the production pin (or on celery-worker after deploy):

  cd backend
  PYTHONPATH=. .venv/bin/python scripts/prod_verify_strikeout_classifier.py

  # Local smoke matching prod pin + Railway AWS env:
  # railway run --service celery-worker -- python scripts/prod_verify_strikeout_classifier.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def main() -> int:
    from app.services.etl.mlb.classification_model import probe_classifier_load

    result = probe_classifier_load()
    print(json.dumps(result, indent=2, default=str))
    if not result.get("ok"):
        print("FAIL: strikeout classifier did not load", file=sys.stderr)
        sk = result.get("sklearn_version")
        if sk and not str(sk).startswith("1.5"):
            print(
                "Hint: artifact expects scikit-learn==1.5.0; "
                f"this environment has {sk}",
                file=sys.stderr,
            )
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
