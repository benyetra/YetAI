#!/usr/bin/env python3
"""Print an externally reachable Postgres URL from Railway service variables."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from urllib.parse import quote_plus


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


def _from_pg_components(vars_map: dict[str, str]) -> str | None:
    host = vars_map.get("PGHOST") or vars_map.get("RAILWAY_TCP_PROXY_DOMAIN")
    port = vars_map.get("PGPORT") or vars_map.get("PORT")
    user = vars_map.get("PGUSER") or vars_map.get("POSTGRES_USER") or "postgres"
    password = vars_map.get("PGPASSWORD") or vars_map.get("POSTGRES_PASSWORD")
    database = (
        vars_map.get("PGDATABASE")
        or vars_map.get("POSTGRES_DB")
        or vars_map.get("DATABASE_NAME")
        or "railway"
    )
    if not host or not password:
        return None
    if ":" not in host and port:
        host = f"{host}:{port}"
    user_q = quote_plus(user)
    pass_q = quote_plus(password)
    return f"postgresql://{user_q}:{pass_q}@{host}/{database}"


def resolve(service_id: str) -> str:
    vars_map = _load_variables(service_id)
    for key in ("DATABASE_PUBLIC_URL", "DATABASE_URL", "POSTGRES_URL"):
        url = vars_map.get(key, "")
        if url and "railway.internal" not in url:
            return url
    built = _from_pg_components(vars_map)
    if built:
        return built
    raise SystemExit(
        f"No public DATABASE_URL on service {service_id}. "
        "Enable public networking on Postgres or set DATABASE_PUBLIC_URL."
    )


def main() -> None:
    service_id = os.environ.get("POSTGRES_SERVICE_ID") or os.environ.get("SERVICE_ID")
    if not service_id:
        print("POSTGRES_SERVICE_ID is required", file=sys.stderr)
        raise SystemExit(1)
    print(resolve(service_id), end="")


if __name__ == "__main__":
    main()
