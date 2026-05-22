#!/usr/bin/env python3
"""Stamp WNBA revisions when schema already exists but alembic_version lags."""

from __future__ import annotations

import os
import subprocess
import sys

from sqlalchemy import create_engine, inspect, text

REVISIONS = (
    ("0107ad42b713", "pred_wnba_team_roster", "table"),
    (
        "e4d591511da1",
        "pred_wnba_today_active_players.expected_minutes",
        "column",
    ),
    (
        "f8a2c91e04bd",
        "pred_wnba_team_roster.unique_wnba_team_roster_team_player",
        "unique",
    ),
)

ORDER = ["74627d53e110", "0107ad42b713", "e4d591511da1", "f8a2c91e04bd"]


def _current_revision(engine) -> str | None:
    with engine.connect() as conn:
        try:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        except Exception:
            return None


def _schema_ready(insp: inspect, kind: str, target: str) -> bool:
    if kind == "table":
        return insp.has_table(target)
    if kind == "column":
        table, column = target.split(".", 1)
        if not insp.has_table(table):
            return False
        return column in {c["name"] for c in insp.get_columns(table)}
    if kind == "unique":
        table, name = target.split(".", 1)
        if not insp.has_table(table):
            return False
        for uc in insp.get_unique_constraints(table):
            if uc.get("name") == name:
                return True
        return False
    raise ValueError(f"unknown kind {kind}")


def _index(revision: str) -> int:
    return ORDER.index(revision)


def main() -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is required", file=sys.stderr)
        raise SystemExit(1)

    engine = create_engine(url)
    insp = inspect(engine)
    current = _current_revision(engine)
    print(f"alembic_version before reconcile: {current!r}")

    for revision, target, kind in REVISIONS:
        if not _schema_ready(insp, kind, target):
            print(f"skip stamp {revision}: schema not ready ({target})")
            continue
        if current is None or _index(current) < _index(revision):
            print(f"stamping {revision} (schema already has {target})")
            subprocess.run(["alembic", "stamp", revision], check=True)
            current = revision

    print(f"alembic_version after reconcile: {current!r}")


if __name__ == "__main__":
    main()
