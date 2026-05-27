"""Tests for notification_router — Twilio + WebSocket dispatch.

Covers:
  - _event_to_dict: dataclass and plain-dict serialization
  - _format_sms_body: SMS headline formatting and length cap
  - _resolve_user_for_pick: DB lookup paths (hit, missing pick, missing bet,
    missing user_id in raw, non-integer user_id, User not found, import error)
  - _push_websocket: dispatches to manager; silent when manager unavailable
  - _send_sms: dispatches via Twilio; skips when no creds or no from-number
  - route_prop_events: end-to-end routing, isolation between channels/events
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

import app.services.notification_router as nr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_event(**overrides):
    """Return a minimal PropEvent-compatible dict."""
    base = dict(
        pick_id="pick-99",
        player_name="Shohei Ohtani",
        stat_key="home_runs",
        new_total=2,
        line=1.5,
        side="over",
        alert_type="threshold_cleared",
        play_description="Solo HR to left.",
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _event_to_dict
# ---------------------------------------------------------------------------


def test_event_to_dict_from_dict():
    d = {"pick_id": "x", "val": 42}
    assert nr._event_to_dict(d) == d


def test_event_to_dict_from_dataclass():
    @dataclass
    class Evt:
        pick_id: str
        score: int

    result = nr._event_to_dict(Evt(pick_id="abc", score=7))
    assert result == {"pick_id": "abc", "score": 7}


def test_event_to_dict_fallback_to_public_attrs():
    class Obj:
        pick_id = "z"
        _private = "hidden"

        def method(self):
            pass

    result = nr._event_to_dict(Obj())
    assert result["pick_id"] == "z"
    assert "_private" not in result
    assert "method" not in result


# ---------------------------------------------------------------------------
# _format_sms_body
# ---------------------------------------------------------------------------


def test_format_sms_body_basic():
    body = nr._format_sms_body(_make_event())
    assert "Shohei Ohtani" in body
    assert "home_runs" in body
    assert "Solo HR" in body


def test_format_sms_body_truncates_to_300():
    ev = _make_event(play_description="X" * 500)
    assert len(nr._format_sms_body(ev)) <= 300


def test_format_sms_body_handles_missing_fields():
    body = nr._format_sms_body({})
    assert "YetAI" in body


# ---------------------------------------------------------------------------
# _resolve_user_for_pick
# ---------------------------------------------------------------------------


def _make_db_objects(user_id=42, raw_user_id=42):
    """Return (session_mock, pick, bet, user) stubs."""
    pick = SimpleNamespace(bet_id="bet-1")
    bet = SimpleNamespace(pikkit_id="bet-1", raw={"user_id": raw_user_id})
    user = SimpleNamespace(
        id=user_id,
        notification_settings={"sms_enabled": True, "phone": "+15550001111"},
    )
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = MagicMock(return_value=False)

    def query_side(model):
        q = MagicMock()
        if model.__name__ == "PikkitPick":
            q.filter_by.return_value.one_or_none.return_value = pick
        elif model.__name__ == "PikkitBet":
            q.filter_by.return_value.one_or_none.return_value = bet
        elif model.__name__ == "User":
            q.filter_by.return_value.one_or_none.return_value = user
        else:
            q.filter_by.return_value.one_or_none.return_value = None
        return q

    session.query = query_side
    return session, pick, bet, user


def _patch_db_and_models(session, pick, bet, user):
    """Patch lazy imports inside _resolve_user_for_pick to inject test doubles."""
    from types import SimpleNamespace as SN

    PikkitPickCls = type("PikkitPick", (), {})
    PikkitBetCls = type("PikkitBet", (), {})
    UserCls = type("User", (), {})

    # Map model class names to the test objects
    def query_side(model):
        q = MagicMock()
        if model.__name__ == "PikkitPick":
            q.filter_by.return_value.one_or_none.return_value = pick
        elif model.__name__ == "PikkitBet":
            q.filter_by.return_value.one_or_none.return_value = bet
        elif model.__name__ == "User":
            q.filter_by.return_value.one_or_none.return_value = user
        else:
            q.filter_by.return_value.one_or_none.return_value = None
        return q

    session.query = query_side

    return patch.dict(
        "sys.modules",
        {
            "app.core.database": SN(SessionLocal=lambda: session),
            "app.models.database_models": SN(User=UserCls),
            "app.models.predictions_models": SN(
                PikkitBet=PikkitBetCls, PikkitPick=PikkitPickCls
            ),
        },
    )


def test_resolve_user_happy_path():
    session, pick, bet, user = _make_db_objects(user_id=42)
    with _patch_db_and_models(session, pick, bet, user):
        result = nr._resolve_user_for_pick("pick-99")
    assert result is not None
    user_id, notif = result
    assert user_id == 42
    assert notif.get("sms_enabled") is True


def test_resolve_user_no_pick_returns_none():
    session, _, bet, user = _make_db_objects()
    with _patch_db_and_models(session, None, bet, user):
        result = nr._resolve_user_for_pick("pick-missing")
    assert result is None


def test_resolve_user_no_bet_returns_none():
    session, pick, _, user = _make_db_objects()
    with _patch_db_and_models(session, pick, None, user):
        result = nr._resolve_user_for_pick("pick-99")
    assert result is None


def test_resolve_user_missing_user_id_in_raw_returns_none():
    session, pick, bet, user = _make_db_objects()
    bet.raw = {}
    with _patch_db_and_models(session, pick, bet, user):
        result = nr._resolve_user_for_pick("pick-99")
    assert result is None


def test_resolve_user_non_integer_user_id_returns_none():
    session, pick, bet, user = _make_db_objects()
    bet.raw = {"user_id": "not-an-int"}
    with _patch_db_and_models(session, pick, bet, user):
        result = nr._resolve_user_for_pick("pick-99")
    assert result is None


def test_resolve_user_user_not_found_returns_none():
    session, pick, bet, _ = _make_db_objects()
    with _patch_db_and_models(session, pick, bet, None):
        result = nr._resolve_user_for_pick("pick-99")
    assert result is None


def test_resolve_user_import_error_returns_none():
    from types import SimpleNamespace as SN

    with patch.dict(
        "sys.modules",
        {"app.core.database": SN(SessionLocal=MagicMock(side_effect=ImportError("no db")))},
    ):
        result = nr._resolve_user_for_pick("pick-99")
    assert result is None


# ---------------------------------------------------------------------------
# _push_websocket
# ---------------------------------------------------------------------------


def test_push_websocket_sends_json_to_manager():
    manager = MagicMock()
    manager.send_personal_message = AsyncMock()
    with patch("app.services.notification_router._get_ws_manager", return_value=manager):
        _run(nr._push_websocket(7, {"type": "prop_event", "data": {"x": 1}}))
    manager.send_personal_message.assert_awaited_once()
    args = manager.send_personal_message.call_args
    payload_str = args.args[0] if args.args else args.kwargs.get("message", "")
    parsed = json.loads(payload_str)
    assert parsed["type"] == "prop_event"
    assert args.args[1] == 7 or args.kwargs.get("user_id") == 7


def test_push_websocket_silent_when_no_manager():
    with patch("app.services.notification_router._get_ws_manager", return_value=None):
        _run(nr._push_websocket(7, {"data": "x"}))  # must not raise


def test_push_websocket_swallows_send_error():
    manager = MagicMock()
    manager.send_personal_message = AsyncMock(side_effect=RuntimeError("closed"))
    with patch("app.services.notification_router._get_ws_manager", return_value=manager):
        _run(nr._push_websocket(7, {}))  # must not raise


# ---------------------------------------------------------------------------
# _send_sms
# ---------------------------------------------------------------------------


def test_send_sms_calls_twilio_with_from_number(monkeypatch):
    client = MagicMock()
    client.messages.create.return_value = MagicMock(sid="SM123")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15559999999")
    monkeypatch.delenv("TWILIO_MESSAGING_SERVICE_SID", raising=False)
    with patch("app.services.notification_router._get_twilio_client", return_value=client):
        _run(nr._send_sms("+15550001111", "test body"))
    client.messages.create.assert_called_once_with(
        to="+15550001111", body="test body", from_="+15559999999"
    )


def test_send_sms_prefers_messaging_service_over_from_number(monkeypatch):
    client = MagicMock()
    client.messages.create.return_value = MagicMock(sid="SM456")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15559999999")
    monkeypatch.setenv("TWILIO_MESSAGING_SERVICE_SID", "MGabc123")
    with patch("app.services.notification_router._get_twilio_client", return_value=client):
        _run(nr._send_sms("+15550001111", "test body"))
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs.get("messaging_service_sid") == "MGabc123"
    assert "from_" not in kwargs


def test_send_sms_silent_when_no_twilio_client():
    with patch("app.services.notification_router._get_twilio_client", return_value=None):
        _run(nr._send_sms("+1555", "msg"))  # must not raise


def test_send_sms_silent_when_no_from_number_or_service_sid(monkeypatch):
    client = MagicMock()
    monkeypatch.delenv("TWILIO_FROM_NUMBER", raising=False)
    monkeypatch.delenv("TWILIO_MESSAGING_SERVICE_SID", raising=False)
    with patch("app.services.notification_router._get_twilio_client", return_value=client):
        _run(nr._send_sms("+1555", "msg"))
    client.messages.create.assert_not_called()


def test_send_sms_swallows_twilio_error(monkeypatch):
    client = MagicMock()
    client.messages.create.side_effect = Exception("network error")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15559999999")
    monkeypatch.delenv("TWILIO_MESSAGING_SERVICE_SID", raising=False)
    with patch("app.services.notification_router._get_twilio_client", return_value=client):
        _run(nr._send_sms("+1555", "msg"))  # must not raise


# ---------------------------------------------------------------------------
# route_prop_events — integration
# ---------------------------------------------------------------------------


def _patch_router(user_id=42, notif=None, ws_ok=True, sms_ok=True):
    """Context manager bundle: patches _resolve_user_for_pick, _push_websocket,
    and _send_sms so route_prop_events can be exercised without real I/O."""
    if notif is None:
        notif = {"sms_enabled": True, "phone": "+15550001111"}

    return (
        patch(
            "app.services.notification_router._resolve_user_for_pick",
            return_value=(user_id, notif),
        ),
        patch(
            "app.services.notification_router._push_websocket",
            new_callable=lambda: lambda: AsyncMock(),
        ),
        patch(
            "app.services.notification_router._send_sms",
            new_callable=lambda: lambda: AsyncMock(),
        ),
    )


def test_route_dispatches_ws_and_sms():
    ev = _make_event()
    resolve = patch(
        "app.services.notification_router._resolve_user_for_pick",
        return_value=(42, {"sms_enabled": True, "phone": "+15550001111"}),
    )
    push_ws = patch(
        "app.services.notification_router._push_websocket",
        new=AsyncMock(),
    )
    send_sms = patch(
        "app.services.notification_router._send_sms",
        new=AsyncMock(),
    )
    with resolve, push_ws as ws_mock, send_sms as sms_mock:
        _run(nr.route_prop_events([ev]))
    ws_mock.assert_awaited_once()
    sms_mock.assert_awaited_once()


def test_route_skips_sms_when_not_opted_in():
    ev = _make_event()
    resolve = patch(
        "app.services.notification_router._resolve_user_for_pick",
        return_value=(42, {"sms_enabled": False, "phone": "+15550001111"}),
    )
    push_ws = patch("app.services.notification_router._push_websocket", new=AsyncMock())
    send_sms = patch("app.services.notification_router._send_sms", new=AsyncMock())
    with resolve, push_ws, send_sms as sms_mock:
        _run(nr.route_prop_events([ev]))
    sms_mock.assert_not_awaited()


def test_route_skips_sms_when_opted_in_but_no_phone():
    ev = _make_event()
    resolve = patch(
        "app.services.notification_router._resolve_user_for_pick",
        return_value=(42, {"sms_enabled": True}),
    )
    push_ws = patch("app.services.notification_router._push_websocket", new=AsyncMock())
    send_sms = patch("app.services.notification_router._send_sms", new=AsyncMock())
    with resolve, push_ws, send_sms as sms_mock:
        _run(nr.route_prop_events([ev]))
    sms_mock.assert_not_awaited()


def test_route_skips_event_with_no_pick_id():
    ev = _make_event(pick_id="")
    resolve = patch(
        "app.services.notification_router._resolve_user_for_pick",
        return_value=(42, {}),
    )
    push_ws = patch("app.services.notification_router._push_websocket", new=AsyncMock())
    send_sms = patch("app.services.notification_router._send_sms", new=AsyncMock())
    with resolve, push_ws as ws_mock, send_sms as sms_mock:
        _run(nr.route_prop_events([ev]))
    ws_mock.assert_not_awaited()
    sms_mock.assert_not_awaited()


def test_route_skips_event_when_user_unresolvable():
    ev = _make_event()
    resolve = patch(
        "app.services.notification_router._resolve_user_for_pick",
        return_value=None,
    )
    push_ws = patch("app.services.notification_router._push_websocket", new=AsyncMock())
    send_sms = patch("app.services.notification_router._send_sms", new=AsyncMock())
    with resolve, push_ws as ws_mock, send_sms as sms_mock:
        _run(nr.route_prop_events([ev]))
    ws_mock.assert_not_awaited()
    sms_mock.assert_not_awaited()


def test_route_continues_after_single_event_ws_failure():
    """WS failure on event 1 must not prevent dispatching event 2."""
    ev1 = _make_event(pick_id="pick-1")
    ev2 = _make_event(pick_id="pick-2")

    call_count = 0

    async def ws_side_effect(user_id, payload):
        nonlocal call_count
        call_count += 1
        if payload["data"].get("pick_id") == "pick-1":
            raise RuntimeError("ws exploded")

    resolve = patch(
        "app.services.notification_router._resolve_user_for_pick",
        return_value=(42, {"sms_enabled": False}),
    )
    push_ws = patch(
        "app.services.notification_router._push_websocket",
        new=ws_side_effect,
    )
    send_sms = patch("app.services.notification_router._send_sms", new=AsyncMock())
    with resolve, push_ws, send_sms:
        _run(nr.route_prop_events([ev1, ev2]))
    assert call_count == 2


def test_route_handles_empty_event_list():
    _run(nr.route_prop_events([]))  # must not raise
