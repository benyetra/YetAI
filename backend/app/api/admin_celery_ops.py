"""Admin Celery ops: health, enqueue, fire-and-wait, verify, task status."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import require_admin
from app.data.celery_tasks import (
    ADMIN_ENQUEUE_TASKS,
    ADMIN_FIREABLE_TASKS,
    FIREABLE_CATALOG,
    PIPELINE_ENQUEUE_CATALOG,
)


router = APIRouter(prefix="/api/admin/celery", tags=["admin-celery"])

PIPELINE_ORCHESTRATORS = ADMIN_ENQUEUE_TASKS


class CeleryEnqueueRequest(BaseModel):
    task_name: str


class CeleryVerifyEtlRequest(BaseModel):
    enqueue_all: bool = False
    wait_seconds: int = 0


class MlbRetrainEnqueueRequest(BaseModel):
    dry_run: bool = False


class MlbHrRebuildEnqueueRequest(BaseModel):
    stage: str
    season: int = 2024
    holdout_date: str = "2024-07-01"
    use_existing_s3: bool = False


@router.get("/broker-check")
async def admin_celery_broker_check(admin_user: dict = Depends(require_admin)):
    """
    Direct Redis PING from the API container (no Celery worker).
    Use this before /health: if broker-check fails, Redis is down for everyone.
    """
    from app.core.redis_broker import mask_redis_target, pick_redis_url, ping_redis_sync

    url = pick_redis_url()
    result = await asyncio.to_thread(ping_redis_sync, url, timeout_s=8.0)
    return {
        "redis_url_target": mask_redis_target(url),
        "uses_railway_internal": "railway.internal" in url,
        "ping": result,
        "hint": (
            "If ping is ok but /health times out, the worker cannot reach Redis "
            "(redeploy celery-worker). If Railway Redis → Database tab cannot connect, "
            "redeploy the Redis service itself."
        ),
    }


@router.get("/health")
async def admin_celery_health(
    admin_user: dict = Depends(require_admin),
    include_games_sync: bool = False,
):
    """Round-trip ping (and optional games sync) through Celery."""
    from celery.exceptions import TimeoutError as CeleryTimeoutError
    from app.celery_app import celery_app

    def _send_and_wait(task: str, timeout: float) -> dict:
        async_result = celery_app.send_task(task)
        try:
            payload = async_result.get(timeout=timeout, disable_sync_subtasks=False)
            return {"status": "ok", "task_id": async_result.id, "result": payload}
        except CeleryTimeoutError:
            return {
                "status": "timeout",
                "task_id": async_result.id,
                "timeout_s": timeout,
                "hint": (
                    "Task was queued (API reached Redis) but no worker consumed it in time. "
                    "Check celery-worker logs for 'Cannot connect to redis'. "
                    "If GET /broker-check also fails, redeploy the Redis service."
                ),
            }
        except Exception as exc:
            return {"status": "error", "task_id": async_result.id, "error": str(exc)}

    ping = await asyncio.to_thread(_send_and_wait, "app.tasks.health.ping", 10.0)
    response = {"ping": ping}
    if include_games_sync:
        response["games_sync"] = await asyncio.to_thread(
            _send_and_wait, "app.tasks.games_sync.sync_games_cache", 180.0
        )
    return response


@router.get("/pipeline-catalog")
async def admin_celery_pipeline_catalog(admin_user: dict = Depends(require_admin)):
    """Orchestrators and sub-tasks allowed for POST /enqueue-task."""
    return {
        "enqueue_tasks": PIPELINE_ENQUEUE_CATALOG,
        "enqueue_subtasks": FIREABLE_CATALOG,
        "fireable_count": len(ADMIN_FIREABLE_TASKS),
    }


@router.get("/fireable-catalog")
async def admin_celery_fireable_catalog(admin_user: dict = Depends(require_admin)):
    """Curated sub-tasks for admin debug runs (POST /run-task)."""
    return {"fireable_tasks": FIREABLE_CATALOG}


@router.post("/enqueue-task")
async def admin_celery_enqueue_task(
    body: CeleryEnqueueRequest,
    admin_user: dict = Depends(require_admin),
):
    """Enqueue an orchestrator or allow-listed sub-task; returns immediately with task_id."""
    from app.celery_app import celery_app

    if body.task_name not in ADMIN_ENQUEUE_TASKS:
        raise HTTPException(
            status_code=400,
            detail=f"task '{body.task_name}' is not in the admin enqueue allow-list",
        )
    async_result = celery_app.send_task(body.task_name)
    return {
        "status": "enqueued",
        "task_id": async_result.id,
        "task_name": body.task_name,
    }


@router.post("/run-task")
async def admin_celery_run_task(
    task_name: str,
    admin_user: dict = Depends(require_admin),
):
    """Fire one allow-listed Celery task and wait for its result."""
    from celery.exceptions import TimeoutError as CeleryTimeoutError
    from app.celery_app import celery_app

    timeout = ADMIN_FIREABLE_TASKS.get(task_name)
    if timeout is None:
        raise HTTPException(
            status_code=400,
            detail=f"task '{task_name}' is not in the admin allow-list",
        )

    def _send_and_wait() -> dict:
        async_result = celery_app.send_task(task_name)
        try:
            payload = async_result.get(timeout=timeout, disable_sync_subtasks=False)
            return {"status": "ok", "task_id": async_result.id, "result": payload}
        except CeleryTimeoutError:
            return {
                "status": "timeout",
                "task_id": async_result.id,
                "timeout_s": timeout,
                "hint": (
                    "Task may still be running on celery-worker (concurrency=1). "
                    f"Poll GET /api/admin/celery/task-status/{async_result.id}"
                ),
            }
        except Exception as exc:
            return {"status": "error", "task_id": async_result.id, "error": str(exc)}

    return await asyncio.to_thread(_send_and_wait)


@router.get("/ml-ops-status")
async def admin_mlb_ml_ops_status(admin_user: dict = Depends(require_admin)):
    """Strikeout training counts, S3 model heads, backtest run index (prod DB)."""
    from app.services.etl.mlb.ml_ops_status import collect_ml_ops_status

    return await asyncio.to_thread(collect_ml_ops_status)


@router.post("/ml-ops/retrain-strikeouts")
async def admin_enqueue_mlb_retrain(
    body: MlbRetrainEnqueueRequest,
    admin_user: dict = Depends(require_admin),
):
    """Enqueue strikeout classifier retrain on celery-worker (prod DATABASE_URL)."""
    from app.celery_app import celery_app

    async_result = celery_app.send_task(
        "app.tasks.etl_pipeline.mlb.retrain_strikeout_classifier",
        kwargs={"dry_run": body.dry_run},
    )
    return {
        "status": "enqueued",
        "task_id": async_result.id,
        "task_name": "app.tasks.etl_pipeline.mlb.retrain_strikeout_classifier",
        "dry_run": body.dry_run,
    }


@router.post("/ml-ops/hr-rebuild")
async def admin_enqueue_mlb_hr_rebuild(
    body: MlbHrRebuildEnqueueRequest,
    admin_user: dict = Depends(require_admin),
):
    """Enqueue one dingerParlay HR rebuild stage (download-pa … train)."""
    from app.celery_app import celery_app
    from app.services.etl.mlb.hr_rebuild_runner import STAGES

    if body.stage not in STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"stage must be one of: {', '.join(STAGES)}",
        )
    async_result = celery_app.send_task(
        "app.tasks.etl_pipeline.mlb.hr_rebuild_stage",
        kwargs={
            "stage": body.stage,
            "season": body.season,
            "holdout_date": body.holdout_date,
            "use_existing_s3": body.use_existing_s3,
        },
    )
    return {
        "status": "enqueued",
        "task_id": async_result.id,
        "task_name": "app.tasks.etl_pipeline.mlb.hr_rebuild_stage",
        "stage": body.stage,
        "season": body.season,
    }


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
    """DB checks for all sport pipelines; optional enqueue of orchestrators."""
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

    ping_response = await admin_celery_health(
        admin_user=admin_user, include_games_sync=False
    )
    verification = await asyncio.to_thread(verify_all_sports)
    api_counts = await asyncio.to_thread(prediction_api_counts)

    return {
        "celery_ping": ping_response.get("ping"),
        "enqueued": enqueued,
        "verification": verification,
        "prediction_api_counts": api_counts,
        "ui_routes": [
            "/predictions/mlb",
            "/predictions/nba",
            "/predictions/wnba",
            "/predictions/nhl",
            "/predictions/nfl",
        ],
        "note": (
            "After enqueue_all, poll each task_id via GET "
            "/api/admin/celery/task-status/{id} until ready, then POST verify-etl again."
        ),
    }
