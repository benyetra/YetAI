"""Admin Celery ops: health, enqueue, fire-and-wait, verify, task status."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import get_current_user
from app.core.service_loader import get_service, is_service_available

# Allow-list of ETL tasks for POST /run-task (sync fire-and-wait).
ADMIN_FIREABLE_TASKS: dict[str, float] = {
    "app.tasks.health.ping": 10.0,
    "app.tasks.games_sync.sync_games_cache": 180.0,
    "app.tasks.etl_pipeline.nba.yesterdays_players": 120.0,
    "app.tasks.etl_pipeline.nba.today_active_players": 120.0,
    "app.tasks.etl_pipeline.nba.update_team_roster": 300.0,
    "app.tasks.etl_pipeline.nba.update_recent_games": 900.0,
    "app.tasks.etl_pipeline.nba.update_injury_status": 120.0,
    "app.tasks.etl_pipeline.nba.update_game_lines": 120.0,
    "app.tasks.etl_pipeline.nba.update_team_stats": 300.0,
    "app.tasks.etl_pipeline.nba.update_player_data": 900.0,
    "app.tasks.etl_pipeline.nba.update_expected_minutes": 120.0,
    "app.tasks.etl_pipeline.nba.generate_predictions": 300.0,
    "app.tasks.etl_pipeline.nba.generate_rebounds_predictions": 600.0,
    "app.tasks.etl_pipeline.nba.generate_assists_predictions": 600.0,
    "app.tasks.etl_pipeline.nba.generate_three_pt_made_predictions": 600.0,
    "app.tasks.etl_pipeline.nba.generate_steals_predictions": 600.0,
    "app.tasks.etl_pipeline.nba.generate_blocks_predictions": 600.0,
    "app.tasks.etl_pipeline.nba.store_actuals": 600.0,
    "app.tasks.etl_pipeline.nba.find_top_performers": 180.0,
    "app.tasks.etl_pipeline.nba.totals_projector": 300.0,
    "app.tasks.etl_pipeline.mlb.strikeouts": 600.0,
    "app.tasks.etl_pipeline.mlb.hits": 600.0,
    "app.tasks.etl_pipeline.mlb.store_strikeout_projections": 600.0,
    "app.tasks.etl_pipeline.mlb.store_strikeout_actuals": 600.0,
    "app.tasks.etl_pipeline.mlb.game_projections": 300.0,
    "app.tasks.etl_pipeline.mlb.batter_projections": 300.0,
    "app.tasks.etl_pipeline.mlb.weather": 180.0,
    "app.tasks.etl_pipeline.mlb.blowouts": 180.0,
    "app.tasks.etl_pipeline.mlb.hr_predictions": 900.0,
    "app.tasks.etl_pipeline.mlb.ev": 600.0,
    "app.tasks.etl_pipeline.nhl.collect_ingest": 1200.0,
    "app.tasks.etl_pipeline.nhl.update_daily_stats": 600.0,
    "app.tasks.etl_pipeline.nhl.daily_predictions": 900.0,
    "app.tasks.etl_pipeline.nhl.collect_goalie_actuals": 300.0,
    "app.tasks.etl_pipeline.nfl.collect_qb_actuals": 600.0,
    "app.tasks.etl_pipeline.nfl.collect_kicker_actuals": 300.0,
    "app.tasks.etl_pipeline.nfl.qb_dynamic": 600.0,
    "app.tasks.etl_pipeline.nfl.qb_betting": 300.0,
    "app.tasks.etl_pipeline.nfl.qb_weekly": 900.0,
    "app.tasks.etl_pipeline.nfl.kickers": 600.0,
}

PIPELINE_ENQUEUE_CATALOG: list[dict[str, str]] = [
    {
        "task_name": "app.tasks.etl_pipeline.run_mlb_update_pipeline",
        "label": "MLB daily projections",
        "sport": "mlb",
        "description": "Strikeouts, hits, boards, weather, blowouts, value bets (EV); optional HR ML when S3 CSVs set.",
    },
    {
        "task_name": "app.tasks.etl_pipeline.run_mlb_store_actuals",
        "label": "MLB store actuals",
        "sport": "mlb",
        "description": "Post-game actuals for game, strikeout, and batter projection tables.",
    },
    {
        "task_name": "app.tasks.etl_pipeline.run_nba_update_pipeline",
        "label": "NBA daily pipeline",
        "sport": "nba",
        "description": "Full NBA ETL: roster, stats, injury, all prop models, game totals.",
    },
    {
        "task_name": "app.tasks.etl_pipeline.run_nfl_update_pipeline",
        "label": "NFL weekly pipeline",
        "sport": "nfl",
        "description": "QB actuals + kicker actuals, QB yards/lines, kicker projections (optional ML blend).",
    },
    {
        "task_name": "app.tasks.etl_pipeline.run_nhl_update_pipeline",
        "label": "NHL daily pipeline",
        "sport": "nhl",
        "description": "Ingest + goalie/SOG/totals with DraftKings edges.",
    },
]

# Subset exposed in admin UI for one-off debug runs (sync, blocks until timeout).
FIREABLE_CATALOG: list[dict[str, str | float]] = [
    {
        "task_name": "app.tasks.etl_pipeline.mlb.ev",
        "label": "MLB value bets (EV)",
        "sport": "mlb",
        "timeout_s": ADMIN_FIREABLE_TASKS["app.tasks.etl_pipeline.mlb.ev"],
        "description": "Refresh pred_value_bets for today (requires ODDS_API_KEY + projections).",
    },
    {
        "task_name": "app.tasks.etl_pipeline.mlb.hr_predictions",
        "label": "MLB HR ML",
        "sport": "mlb",
        "timeout_s": ADMIN_FIREABLE_TASKS["app.tasks.etl_pipeline.mlb.hr_predictions"],
        "description": "HR ML: build lineup/features (MLB_HR_AUTO_BUILD=1) then predict_today → pred_daily_hr_predictions.",
    },
    {
        "task_name": "app.tasks.etl_pipeline.mlb.strikeouts",
        "label": "MLB strikeouts",
        "sport": "mlb",
        "timeout_s": ADMIN_FIREABLE_TASKS["app.tasks.etl_pipeline.mlb.strikeouts"],
        "description": "Rebuild pred_pitcher for today's slate (run before store K).",
    },
    {
        "task_name": "app.tasks.etl_pipeline.mlb.store_strikeout_projections",
        "label": "MLB archive K projections",
        "sport": "mlb",
        "timeout_s": ADMIN_FIREABLE_TASKS[
            "app.tasks.etl_pipeline.mlb.store_strikeout_projections"
        ],
        "description": "Copy pred_pitcher → pred_strikeout_projections for today.",
    },
    {
        "task_name": "app.tasks.etl_pipeline.mlb.store_strikeout_actuals",
        "label": "MLB archive K actuals",
        "sport": "mlb",
        "timeout_s": ADMIN_FIREABLE_TASKS[
            "app.tasks.etl_pipeline.mlb.store_strikeout_actuals"
        ],
        "description": "Post-game K actuals → pred_strikeout_actuals (yesterday).",
    },
    {
        "task_name": "app.tasks.etl_pipeline.nhl.daily_predictions",
        "label": "NHL daily predictions",
        "sport": "nhl",
        "timeout_s": ADMIN_FIREABLE_TASKS[
            "app.tasks.etl_pipeline.nhl.daily_predictions"
        ],
        "description": "Goalie, SOG, team totals automation.",
    },
    {
        "task_name": "app.tasks.etl_pipeline.nfl.kickers",
        "label": "NFL kickers",
        "sport": "nfl",
        "timeout_s": ADMIN_FIREABLE_TASKS["app.tasks.etl_pipeline.nfl.kickers"],
        "description": "Kicker projections; ML blend when NFL_MODELS_S3_PREFIX or local models.",
    },
]

# Orchestrators + curated sub-tasks (same names as POST /run-task allow-list).
ADMIN_ENQUEUE_TASKS: frozenset[str] = frozenset(
    {entry["task_name"] for entry in PIPELINE_ENQUEUE_CATALOG}
    | set(ADMIN_FIREABLE_TASKS.keys())
)


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

PIPELINE_ORCHESTRATORS = ADMIN_ENQUEUE_TASKS


class CeleryEnqueueRequest(BaseModel):
    task_name: str


class CeleryVerifyEtlRequest(BaseModel):
    enqueue_all: bool = False
    wait_seconds: int = 0


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
            "/predictions/nhl",
            "/predictions/nfl",
        ],
        "note": (
            "After enqueue_all, poll each task_id via GET "
            "/api/admin/celery/task-status/{id} until ready, then POST verify-etl again."
        ),
    }
