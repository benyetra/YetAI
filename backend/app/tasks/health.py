"""Trivial health-check task — used by deploy verification + Celery wiring tests."""
from datetime import datetime

from app.celery_app import celery_app


@celery_app.task(name="app.tasks.health.ping")
def ping() -> dict:
    """Confirms Celery wiring. Invokable via celery.send_task or .apply()."""
    return {"status": "ok", "ts": datetime.utcnow().isoformat() + "Z"}
