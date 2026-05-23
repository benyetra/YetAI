"""Integration tests for PATCH/POST admin pipeline schedule endpoints.

Uses dependency_overrides to bypass require_admin + supply a mock DB
session, isolating the route logic from actual DB and auth.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.core.auth import require_admin
from app.core.database import get_db


NBA_TASK = "app.tasks.etl_pipeline.run_nba_update_pipeline"


@pytest.fixture
def admin_client(monkeypatch):
    """TestClient with require_admin bypassed and get_db swapped for a mock."""
    db = MagicMock()

    async def _admin():
        return {"id": 1, "user_id": 1, "is_admin": True}

    def _db():
        yield db

    m.app.dependency_overrides[require_admin] = _admin
    m.app.dependency_overrides[get_db] = _db
    try:
        yield TestClient(m.app), db
    finally:
        m.app.dependency_overrides.clear()


def test_patch_rejects_unknown_task(admin_client):
    client, _ = admin_client
    r = client.patch(
        "/api/admin/pipelines/not.a.real.task/schedule",
        json={"hour": 3, "minute": 30, "enabled": True},
    )
    assert r.status_code == 400


def test_patch_rejects_out_of_range_values(admin_client):
    client, _ = admin_client
    r = client.patch(
        f"/api/admin/pipelines/{NBA_TASK}/schedule",
        json={"hour": 25, "minute": 0, "enabled": True},
    )
    assert r.status_code == 422  # pydantic validation


def test_patch_calls_upsert_for_editable_task(admin_client, monkeypatch):
    """Body forwarded to ovr.upsert and the result is returned as JSON."""
    from app.services import pipeline_schedule_overrides as ovr

    client, _db = admin_client
    fake_row = MagicMock(
        task_name=NBA_TASK,
        hour=6,
        minute=15,
        enabled=True,
    )
    monkeypatch.setattr(ovr, "upsert", MagicMock(return_value=fake_row))

    r = client.patch(
        f"/api/admin/pipelines/{NBA_TASK}/schedule",
        json={"hour": 6, "minute": 15, "enabled": True},
    )
    assert r.status_code == 200
    assert r.json() == {
        "task_name": NBA_TASK,
        "hour": 6,
        "minute": 15,
        "enabled": True,
    }


def test_reset_rejects_unknown_task(admin_client):
    client, _ = admin_client
    r = client.post("/api/admin/pipelines/not.a.real.task/schedule/reset")
    assert r.status_code == 400


def test_reset_returns_deleted_flag(admin_client, monkeypatch):
    from app.services import pipeline_schedule_overrides as ovr

    client, _ = admin_client
    monkeypatch.setattr(ovr, "delete", MagicMock(return_value=True))

    r = client.post(f"/api/admin/pipelines/{NBA_TASK}/schedule/reset")
    assert r.status_code == 200
    assert r.json() == {"reset": True}
