"""Daily alert when the Odds API key is projected to run out before the cycle resets.

Projection uses the bill (free quota call), see odds_credit_report. One
AdminNotification (+ SMS) per UTC day, delivered through the settlement alert's `_send`.
"""

import logging
import os

from app.celery_app import celery_app
from app.core.database import SessionLocal
from app.services import odds_credit_report as cr
from app.services.odds_api_sync import read_live_quota
from app.tasks.yetai_settlement_alert import _last_alert, _send

log = logging.getLogger(__name__)

TASK_NAME = "odds_credits.runout_alert"


def _enabled() -> bool:
    return os.getenv("ODDS_CREDIT_ALERTS_ENABLED", "true").strip().lower() not in (
        "false",
        "0",
        "no",
        "off",
    )


def build_message(s: dict) -> str:
    return (
        f"[YetAI] Odds API credits: {s['remaining']:,} left, "
        f"~{s['rate_7d']:,.0f}/day ({s['rate_source']}, 7d) -> run out "
        f"~{s['projected_runout']}, before reset {s['next_reset']}. "
        f"Recommended daily budget {s['recommended_daily']:,}."
    )


@celery_app.task(name=TASK_NAME)
def runout_alert() -> dict:
    if not _enabled():
        return {"sent": False, "reason": "disabled"}
    db = SessionLocal()
    try:
        quota = read_live_quota()
        if not quota:
            return {"sent": False, "reason": "quota unavailable"}
        today = cr.utc_today()
        cr.snapshot_quota(quota, today.isoformat())
        s = cr.credits_summary(today, quota)
        if not s["runs_out_before_reset"]:
            return {"sent": False, "runout": s["projected_runout"]}
        signature = f"odds-runout:{today.isoformat()}"
        last = _last_alert(db, TASK_NAME)
        if last and (last.extra or {}).get("signature") == signature:
            return {"sent": False, "reason": "already sent today"}
        _send(
            db,
            build_message(s),
            signature,
            task_name=TASK_NAME,
            label="Odds API credits",
        )
        return {"sent": True, "runout": s["projected_runout"]}
    except Exception as e:
        log.exception("%s failed", TASK_NAME)
        return {"sent": False, "error": str(e)}
    finally:
        db.close()
