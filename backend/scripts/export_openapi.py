#!/usr/bin/env python3
"""
Export YetAI OpenAPI specs for developers and AI agents.

Writes:
  docs/api/openapi.json         — full API
  docs/api/openapi-public.json  — consumer + agent routes
  docs/api/openapi-admin.json   — admin + debug routes

Run from repo root:
  cd backend && PYTHONPATH=. python scripts/export_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
DOCS_API = REPO_ROOT / "docs" / "api"

sys.path.insert(0, str(BACKEND_ROOT))


def main() -> int:
    from app.main import app
    from app.openapi_config import export_openapi_variants

    variants = export_openapi_variants(app)
    DOCS_API.mkdir(parents=True, exist_ok=True)

    outputs = {
        "openapi.json": variants["full"],
        "openapi-public.json": variants["public"],
        "openapi-admin.json": variants["admin"],
    }
    for name, schema in outputs.items():
        path = DOCS_API / name
        path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
        paths = len(schema.get("paths", {}))
        print(f"Wrote {path} ({paths} paths)")

    public_paths = len(variants["public"].get("paths", {}))
    admin_paths = len(variants["admin"].get("paths", {}))
    if public_paths < 10:
        print("WARNING: public spec has very few paths", file=sys.stderr)
        return 1
    if admin_paths < 3:
        print("WARNING: admin spec has very few paths", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
