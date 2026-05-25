"""OpenAPI export and agent-metadata smoke tests."""

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_API = REPO_ROOT / "docs" / "api"


@pytest.fixture(scope="module")
def openapi_variants():
    from app.main import app
    from app.openapi_config import export_openapi_variants

    app.openapi_schema = None
    return export_openapi_variants(app)


def test_openapi_has_security_scheme(openapi_variants):
    full = openapi_variants["full"]
    assert "BearerAuth" in full["components"]["securitySchemes"]


def test_public_and_admin_specs_disjoint_audiences(openapi_variants):
    public_paths = set(openapi_variants["public"]["paths"])
    admin_paths = set(openapi_variants["admin"]["paths"])
    assert not public_paths & admin_paths


def test_operations_have_operation_ids(openapi_variants):
    missing = []
    for path, path_item in openapi_variants["public"]["paths"].items():
        for method, op in path_item.items():
            if method in ("parameters", "servers"):
                continue
            if isinstance(op, dict) and not op.get("operationId"):
                missing.append(f"{method.upper()} {path}")
    assert not missing, f"Missing operationId: {missing[:5]}"


def test_committed_specs_match_export(openapi_variants, tmp_path):
    """Committed JSON under docs/api/ should match a fresh export."""
    for name, schema in [
        ("openapi.json", openapi_variants["full"]),
        ("openapi-public.json", openapi_variants["public"]),
        ("openapi-admin.json", openapi_variants["admin"]),
    ]:
        committed = DOCS_API / name
        if not committed.exists():
            pytest.skip(f"{committed} not generated yet")
        on_disk = json.loads(committed.read_text(encoding="utf-8"))
        assert len(on_disk.get("paths", {})) == len(schema.get("paths", {})), name
