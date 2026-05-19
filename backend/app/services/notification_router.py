"""
Notification router — single entry point for prop-event alerts.

Per Development-vir: no Discord. Two delivery channels supported:
  1. WebSocket — push to any connected `/ws/{user_id}` client (live UI updates).
  2. Twilio SMS — for users who've opted in via `User.notification_settings`.

The router is async so Celery callers wrap it with `asyncio.run(...)`.

Both channels are best-effort and isolated: one channel's failure must not
block the other, and a per-event failure must not abort the whole batch.
"""

import asyncio
import json
import logging
import os
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterable, Optional, Tuple

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Lazy singletons
# --------------------------------------------------------------------------- #

_twilio_client = None
_twilio_init_attempted = False


def _get_twilio_client():
    """Lazy-init the Twilio REST client. Returns None if creds are missing
    or the client fails to construct. Cached so we don't repeatedly attempt.
    """
    global _twilio_client, _twilio_init_attempted
    if _twilio_init_attempted:
        return _twilio_client
    _twilio_init_attempted = True

    try:
        from app.core.config import settings

        sid = getattr(settings, "TWILIO_ACCOUNT_SID", None)
        token = getattr(settings, "TWILIO_AUTH_TOKEN", None)
        if not sid or not token:
            logger.info(
                "Twilio creds not configured (TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN); "
                "SMS dispatch disabled."
            )
            return None

        from twilio.rest import Client

        _twilio_client = Client(sid, token)
        logger.info("Twilio client initialized for prop-event SMS dispatch.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to initialize Twilio client: %s", exc)
        _twilio_client = None
    return _twilio_client


def _get_ws_manager():
    """Return the FastAPI app's WebSocket ConnectionManager singleton.

    Imported lazily to avoid the heavy `app.main` import at module load.
    Returns None if the manager isn't reachable (e.g., during unit tests
    that don't boot the FastAPI app).
    """
    try:
        from app.main import ws_manager  # type: ignore

        return ws_manager
    except Exception as exc:  # noqa: BLE001
        logger.warning("ConnectionManager unavailable for WS dispatch: %s", exc)
        return None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _event_to_dict(ev: Any) -> Dict[str, Any]:
    """Best-effort conversion of a PropEvent (or any object) to JSON-safe dict."""
    if is_dataclass(ev):
        return asdict(ev)
    if isinstance(ev, dict):
        return dict(ev)
    # Fallback: pluck public attributes
    return {
        k: getattr(ev, k)
        for k in dir(ev)
        if not k.startswith("_") and not callable(getattr(ev, k, None))
    }


def _resolve_user_for_pick(pick_id: str) -> Optional[Tuple[int, Dict[str, Any]]]:
    """Resolve the YetAI user who owns a given pick_id.

    Returns (user_id, notification_settings) or None if the user can't be
    resolved. Each lookup opens its own short-lived SessionLocal.

    NOTE (gap, see Development-vir backlog): the current Pikkit schema has
    no foreign key from PikkitBet to User. We attempt a best-effort lookup
    inside `PikkitBet.raw` JSONB for a `user_id` (or common variants) key.
    If that fails, this function returns None and the caller skips the event.
    A persistent fix needs either a dedicated mapping table or a User FK
    added to PikkitBet — tracked separately and intentionally not faked here.
    """
    try:
        from app.core.database import SessionLocal
        from app.models.database_models import User
        from app.models.predictions_models import PikkitBet, PikkitPick
    except Exception as exc:  # noqa: BLE001
        logger.warning("User-lookup imports failed: %s", exc)
        return None

    try:
        with SessionLocal() as session:
            pick = session.query(PikkitPick).filter_by(pikkit_id=pick_id).one_or_none()
            if pick is None:
                logger.debug("No PikkitPick found for pick_id=%s", pick_id)
                return None

            bet = (
                session.query(PikkitBet).filter_by(pikkit_id=pick.bet_id).one_or_none()
            )
            if bet is None:
                logger.debug("No PikkitBet found for bet_id=%s", pick.bet_id)
                return None

            raw = bet.raw or {}
            # TODO(Development-vir backlog): replace this best-effort raw probe
            # with a real user FK / mapping table once the schema is extended.
            user_ref = (
                raw.get("user_id")
                or raw.get("yetai_user_id")
                or raw.get("owner_user_id")
                or (raw.get("user") or {}).get("id")
            )
            if user_ref is None:
                logger.warning(
                    "PikkitBet %s has no user_id in raw JSONB; cannot route event for pick %s",
                    bet.pikkit_id,
                    pick_id,
                )
                return None

            try:
                user_id = int(user_ref)
            except (TypeError, ValueError):
                logger.warning(
                    "PikkitBet %s user_id is non-integer: %r", bet.pikkit_id, user_ref
                )
                return None

            user = session.query(User).filter_by(id=user_id).one_or_none()
            if user is None:
                logger.warning(
                    "User id=%s referenced by bet %s not found", user_id, bet.pikkit_id
                )
                return None

            # Snapshot the settings while the session is open.
            settings_dict = dict(user.notification_settings or {})
            return user_id, settings_dict
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error resolving user for pick %s: %s", pick_id, exc)
        return None


def _format_sms_body(ev_data: Dict[str, Any]) -> str:
    """Render a short, SMS-sized headline for a PropEvent dict."""
    player = ev_data.get("player_name") or "Player"
    stat = ev_data.get("stat_key") or "stat"
    new_total = ev_data.get("new_total")
    line = ev_data.get("line")
    side = (ev_data.get("side") or "").upper()
    alert_type = ev_data.get("alert_type") or "update"
    desc = ev_data.get("play_description") or ""

    head = (
        f"[YetAI] {player} {stat} now {new_total} (line {line} {side}) — {alert_type}"
    )
    if desc:
        head = f"{head}: {desc}"
    # SMS segments are 160 chars; trim defensively.
    return head[:300]


async def _push_websocket(user_id: int, payload: Dict[str, Any]) -> None:
    """Best-effort push of `payload` to the user's WS session, if connected."""
    manager = _get_ws_manager()
    if manager is None:
        return
    try:
        message = json.dumps(payload, default=str)
        await manager.send_personal_message(message, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("WebSocket push failed for user %s: %s", user_id, exc)


async def _send_sms(to_number: str, body: str) -> None:
    """Best-effort Twilio SMS send. Runs the blocking client call in a thread."""
    client = _get_twilio_client()
    if client is None:
        return

    from_number = os.environ.get("TWILIO_FROM_NUMBER")
    messaging_service_sid = os.environ.get("TWILIO_MESSAGING_SERVICE_SID")
    if not from_number and not messaging_service_sid:
        logger.warning(
            "Neither TWILIO_FROM_NUMBER nor TWILIO_MESSAGING_SERVICE_SID set; skipping SMS to %s",
            to_number,
        )
        return

    def _do_send():
        kwargs: Dict[str, Any] = {"to": to_number, "body": body}
        if messaging_service_sid:
            kwargs["messaging_service_sid"] = messaging_service_sid
        else:
            kwargs["from_"] = from_number
        return client.messages.create(**kwargs)

    try:
        await asyncio.to_thread(_do_send)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Twilio SMS to %s failed: %s", to_number, exc)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


async def route_prop_events(events: Iterable) -> None:
    """Dispatch each prop event to all relevant notification channels.

    `events` is an iterable of PropEvent dataclasses from
    app.services.live_betting.prop_events. For each event:

      1. Resolve the user behind ev.pick_id (PikkitPick -> PikkitBet ->
         User via raw JSONB; see _resolve_user_for_pick TODO).
      2. If a WebSocket session is connected at /ws/{user_id}, push a
         structured JSON message.
      3. If the user has `notification_settings.sms_enabled` and a phone
         number on file, send a Twilio SMS.

    Both channels are best-effort and isolated: any failure is logged and
    swallowed so a single bad event can't poison the batch or block the
    sibling channel.
    """
    for ev in events:
        try:
            ev_data = _event_to_dict(ev)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to serialize prop event %r: %s", ev, exc)
            continue

        pick_id = ev_data.get("pick_id")
        logger.info("prop_event: %s", ev_data)

        if not pick_id:
            logger.warning("Skipping prop event with no pick_id: %s", ev_data)
            continue

        resolved = _resolve_user_for_pick(pick_id)
        if resolved is None:
            # User-lookup gap already logged inside the helper.
            continue
        user_id, notif_settings = resolved

        # 1) WebSocket push — best effort.
        ws_payload = {"type": "prop_event", "data": ev_data}
        try:
            await _push_websocket(user_id, ws_payload)
        except Exception as exc:  # noqa: BLE001
            logger.exception("WS dispatch error for user %s: %s", user_id, exc)

        # 2) Twilio SMS — best effort, gated on opt-in + phone presence.
        try:
            sms_enabled = bool(notif_settings.get("sms_enabled"))
            phone = (
                notif_settings.get("phone")
                or notif_settings.get("phone_number")
                or notif_settings.get("sms_number")
            )
            if sms_enabled and phone:
                body = _format_sms_body(ev_data)
                await _send_sms(str(phone), body)
            elif sms_enabled and not phone:
                logger.info(
                    "User %s has sms_enabled but no phone number; skipping SMS.",
                    user_id,
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("SMS dispatch error for user %s: %s", user_id, exc)
