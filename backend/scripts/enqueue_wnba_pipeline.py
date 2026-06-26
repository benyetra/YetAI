#!/usr/bin/env python3
"""Enqueue run_wnba_update_pipeline via Celery broker or YetAI admin API."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from app.celery_app import celery_app

TASK = "app.tasks.etl_pipeline.run_wnba_update_pipeline"
DEFAULT_API = os.getenv("YETAI_API", "https://api.yetai.app")


def _admin_token(api: str) -> str:
    token = (os.getenv("YETAI_ADMIN_JWT") or os.getenv("ADMIN_TOKEN") or "").strip()
    if token:
        return token
    email = os.getenv("YETAI_ADMIN_EMAIL")
    password = os.getenv("YETAI_ADMIN_PASSWORD")
    if not email or not password:
        raise RuntimeError(
            "Set YETAI_ADMIN_JWT or YETAI_ADMIN_EMAIL + YETAI_ADMIN_PASSWORD"
        )
    payload = json.dumps({"email_or_username": email, "password": password}).encode()
    req = urllib.request.Request(
        f"{api.rstrip('/')}/api/auth/login",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    token = data.get("access_token") or data.get("token")
    if not token:
        raise RuntimeError("login response missing access_token")
    return token


def _enqueue_via_admin_api(api: str) -> str:
    token = _admin_token(api)
    body = json.dumps({"task_name": TASK}).encode()
    req = urllib.request.Request(
        f"{api.rstrip('/')}/api/admin/celery/enqueue-task",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode())
    task_id = payload.get("task_id")
    if not task_id:
        raise RuntimeError(f"enqueue response missing task_id: {payload}")
    return task_id


def main() -> None:
    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if redis_url and "railway.internal" not in redis_url:
        try:
            result = celery_app.send_task(TASK)
            print(f"enqueued {result.id}")
            return
        except Exception as exc:
            print(f"celery enqueue failed ({exc}); trying admin API")

    task_id = _enqueue_via_admin_api(DEFAULT_API)
    print(f"enqueued {task_id} via admin API")


if __name__ == "__main__":
    main()
