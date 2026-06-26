#!/usr/bin/env python3
"""Enqueue run_wnba_update_pipeline on the Celery broker (Railway worker)."""

from app.celery_app import celery_app

TASK = "app.tasks.etl_pipeline.run_wnba_update_pipeline"


def main() -> None:
    result = celery_app.send_task(TASK)
    print(f"enqueued {result.id}")


if __name__ == "__main__":
    main()
