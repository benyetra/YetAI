#!/usr/bin/env python3
"""Resolve a public Redis broker URL from Railway project variables."""

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


def _list_service_ids() -> list[str]:
    proc = subprocess.run(
        ["railway", "service", "list", "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    if isinstance(data, list):
        return [str(item.get("id")) for item in data if item.get("id")]
    if isinstance(data, dict) and "services" in data:
        return [str(s.get("id")) for s in data["services"] if s.get("id")]
    return []


def resolve_public_redis_url() -> str:
    service_ids = _list_service_ids()
    fallback_ids = [
        os.environ.get("CELERY_SERVICE_ID"),
        os.environ.get("API_SERVICE_ID"),
        "9b9982f4-82b7-4e0f-88a0-3212221fecf4",
        "9fe8f0dc-96ac-408f-9960-950768e6eb49",
    ]
    for sid in fallback_ids:
        if sid and sid not in service_ids:
            service_ids.append(sid)

    for service_id in service_ids:
        try:
            vars_map = _load_variables(service_id)
        except subprocess.CalledProcessError:
            continue
        for key in ("REDIS_PUBLIC_URL", "REDIS_URL", "REDIS_PRIVATE_URL"):
            value = (vars_map.get(key) or "").strip()
            if value and "railway.internal" not in value:
                return value
    raise SystemExit(
        "No public REDIS URL found in Railway project. "
        "Expose REDIS_PUBLIC_URL on the Redis plugin or a linked service."
    )


def main() -> None:
    print(resolve_public_redis_url(), end="")


if __name__ == "__main__":
    main()
