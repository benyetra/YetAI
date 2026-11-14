"""Celery worker command for a Railway service, chosen by CELERY_ROLE.

    CELERY_ROLE unset or "all"  today's celery-worker: beat + every queue
    CELERY_ROLE=etl             beat + the default queue only
    CELERY_ROLE=bets            the yetai_bets queue only, never beat

Both services run the same image with start command
``bash /app/scripts/railway-celery.sh``, which execs ``python -m app.worker_role``.
Extra arguments are appended. Rollout: docs/runbooks/bets-worker.md.
"""

from __future__ import annotations

import os
import sys

# Kept literal (not imported from app.celery_app) so building the command does not
# import the whole app; tests assert they match celery_app's names.
DEFAULT_QUEUE = "celery"
BETS_QUEUE = "yetai_bets"

_BASE = ["celery", "-A", "app.celery_app", "worker"]
# Exactly the production start command before the bets worker existed.
_ETL_FLAGS = [
    "--beat",
    "--loglevel=info",
    "--concurrency=1",
    "--max-memory-per-child=800000",
    "--max-tasks-per-child=8",
]
ROLES = {
    "all": _ETL_FLAGS,
    "etl": _ETL_FLAGS + ["-Q", DEFAULT_QUEUE, "-n", "etl@%h"],
    "bets": [
        "--loglevel=info",
        "-Q",
        BETS_QUEUE,
        "--concurrency=1",
        "--max-memory-per-child=400000",
        "--max-tasks-per-child=50",
        "-n",
        "bets@%h",
    ],
}


def build_argv(role: str | None, extra: list[str] | None = None) -> list[str]:
    role = (role or "").strip().lower() or "all"
    if role not in ROLES:
        raise SystemExit(f"CELERY_ROLE={role!r}: expected one of {sorted(ROLES)}")
    extra = list(extra or [])
    if role == "bets" and any(a in ("-B", "--beat") for a in extra):
        # A second beat would send every scheduled task twice.
        raise SystemExit("CELERY_ROLE=bets never runs beat")
    return _BASE + ROLES[role] + extra


if __name__ == "__main__":
    argv = build_argv(os.getenv("CELERY_ROLE"), sys.argv[1:])
    print("worker_role: " + " ".join(argv), file=sys.stderr, flush=True)
    os.execvp(argv[0], argv)
