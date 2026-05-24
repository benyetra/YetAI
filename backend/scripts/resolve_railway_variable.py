#!/usr/bin/env python3
"""Print a Railway service variable (e.g. ODDS_API_KEY from celery-worker)."""

from __future__ import annotations

import json
import os
import subprocess
import sys


def _load_variables(service_id: str) -> dict[str, str]:
    proc = subprocess.run(
        ["railway", "variable", "list", "--service", service_id, "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}
    return {str(item["name"]): str(item["value"]) for item in data}


_ALIASES = {
    "ODDS_API_KEY": ("ODDS_API_KEY", "ODDS_API"),
}


def resolve(service_id: str, name: str) -> str:
    vars_map = _load_variables(service_id)
    for key in _ALIASES.get(name, (name,)):
        value = vars_map.get(key, "").strip()
        if value:
            return value
    raise SystemExit(f"{name} not found on Railway service {service_id}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: resolve_railway_variable.py <VAR_NAME>")
    service_id = os.environ.get("RAILWAY_SERVICE_ID") or os.environ.get(
        "CELERY_SERVICE_ID"
    )
    if not service_id:
        raise SystemExit("Set RAILWAY_SERVICE_ID or CELERY_SERVICE_ID")
    print(resolve(service_id, sys.argv[1]), end="")


if __name__ == "__main__":
    main()
