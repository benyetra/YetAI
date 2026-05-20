"""Admin Celery ops: task polling and production ETL verification."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import get_current_user
from app.core.service_loader import get_service, is_service_available


async def require_admin(current_user: dict = Depends(get_current_user)):
    """Require admin privileges (same rules as main.require_admin)."""
    if is_service_available("auth_service"):
        auth_service = get_service("auth_service")
        user_data = await auth_service.get_user_by_id(
            current_user.get("id") or current_user.get("user_id")
        )
        if not user_data or not user_data.get("is_admin", False):
            raise HTTPException(status_code=403, detail="Admin privileges required")
        return user_data
    if (current_user.get("id") or current_user.get("user_id")) == 8:
        return current_user
    raise HTTPException(status_code=403, detail="Admin privileges required")


router = APIRouter(prefix="/api/admin/celery", tags=["admin-celery"])

PIPELINE_ORCHESTRATORS: frozenset[str] = frozenset(
    {
        "app.tasks.etl_pipeline.run_mlb_update_pipeline",
        "app.tasks.etl_pipeline.run_mlb_store_actuals",
        "app.tasks.etl_pipeline.run_nba_update_pipeline",
        "app.tasks.etl_pipeline.run_nfl_update_pipeline",
        "app.tasks.etl_pipeline.run_nhl_update_pipeline",
    }
)


class CeleryVerifyEtlRequest(BaseModel):
    enqueue_all: bool = False
    wait_seconds: int = 0


@router.get("/task-status/{task_id}")
async def admin_celery_task_status(
    task_id: str,
    admin_user: dict = Depends(require_admin),
):
    """Poll a Celery task result (orchestrator completion)."""
    from celery.exceptions import TimeoutError as CeleryTimeoutError
    from app.celery_app import celery_app

    async_result = celery_app.AsyncResult(task_id)

    def _read() -> dict:
        if async_result.ready():
            try:
                payload = async_result.get(timeout=1.0, disable_sync_subtasks=False)
                return {"state": async_result.state, "ready": True, "result": payload}
            except CeleryTimeoutError:
                return {"state": async_result.state, "ready": True, "result": None}
            except Exception as exc:
                return {
                    "state": async_result.state,
                    "ready": True,
                    "error": str(exc),
                }
        return {"state": async_result.state, "ready": False}

    return {"task_id": task_id, **await asyncio.to_thread(_read)}


@router.post("/verify-etl")
async def admin_celery_verify_etl(
    body: CeleryVerifyEtlRequest | None = None,
    admin_user: dict = Depends(require_admin),
):
    """DB checks for all four sport pipelines; optional enqueue of orchestrators."""
    from celery.exceptions import TimeoutError as CeleryTimeoutError
    from app.celery_app import celery_app
    from app.services.etl.prod_verification import (
        prediction_api_counts,
        verify_all_sports,
    )

    body = body or CeleryVerifyEtlRequest()
    enqueued: list[dict[str, str]] = []

    if body.enqueue_all:
        for task_name in sorted(PIPELINE_ORCHESTRATORS):
            async_result = celery_app.send_task(task_name)
            enqueued.append({"task_name": task_name, "task_id": async_result.id})

    if body.wait_seconds > 0 and enqueued:
        await asyncio.sleep(min(body.wait_seconds, 3600))

    def _ping() -> dict:
        async_result = celery_app.send_task("app.tasks.health.ping")
        try:
            payload = async_result.get(timeout=10.0, disable_sync_subtasks=False)
            return {"status": "ok", "task_id": async_result.id, "result": payload}
        except CeleryTimeoutError:
            return {"status": "timeout", "task_id": async_result.id, "timeout_s": 10.0}
        except Exception as exc:
            return {"status": "error", "task_id": async_result.id, "error": str(exc)}

    ping = await asyncio.to_thread(_ping)
    verification = await asyncio.to_thread(verify_all_sports)
    api_counts = await asyncio.to_thread(prediction_api_counts)

    return {
        "celery_ping": ping,
        "enqueued": enqueued,
        "verification": verification,
        "prediction_api_counts": api_counts,
        "ui_routes": [
            "/predictions/mlb",
            "/predictions/nba",
            "/predictions/nhl",
            "/predictions/nfl",
        ],
        "note": (
            "After enqueue_all, poll each task_id via GET "
            "/api/admin/celery/task-status/{id} until ready, then POST verify-etl again."
        ),
    }
