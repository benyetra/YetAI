"""
Notification router — single entry point for prop-event alerts.

Per Development-vir: no Discord. Two delivery channels supported:
  1. WebSocket — push to any connected `/ws/{user_id}` client (live UI updates).
  2. Twilio SMS — for users who've opted in via `User.notification_settings`.

The router is async so Celery callers wrap it with `asyncio.run(...)`.
"""
import logging
from typing import Iterable

logger = logging.getLogger(__name__)


async def route_prop_events(events: Iterable) -> None:
    """Dispatch each prop event to all relevant notification channels.

    `events` is an iterable of PropEvent dataclasses from
    app.services.live_betting.prop_events. Each PropEvent carries the pick_id
    + bet_id + delta + summary text — enough for downstream channels to
    materialize a user-facing message.

    For now this is a stub that logs each event. The full implementation
    (Twilio dispatch + WebSocket push) lands in a follow-up issue once the
    Celery worker is actually running against Railway.
    """
    for ev in events:
        logger.info("prop_event: %s", ev)
        # TODO (follow-up issue):
        #   1. Look up the user behind ev.pick_id via SessionLocal -> PikkitBet -> User.
        #   2. If user.notification_settings.sms_enabled, send via Twilio.
        #   3. Push the event to /ws/{user_id} WebSocket subscribers.
