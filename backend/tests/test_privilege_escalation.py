"""Privilege escalation hardening: profile mass-assignment and email HTML escape."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app as production_app
from app.services.auth_service_db import AuthServiceDB
from app.services.email_service import EmailService, _safe_display_name


class TestProfilePrivilegeEscalation:
    def test_profile_update_rejects_admin_and_elite_via_schema(self):
        from app.core import auth as auth_mod
        from app.main import app

        async def _fake_user():
            return {"id": 99, "user_id": 99, "is_admin": False}

        app.dependency_overrides[auth_mod.get_current_user] = _fake_user
        try:
            with (
                patch("app.main.is_service_available", return_value=True),
                patch("app.main.get_service") as mock_get_service,
            ):
                auth = MagicMock()
                auth.update_user = AsyncMock()
                mock_get_service.return_value = auth
                client = TestClient(production_app)

                response = client.put(
                    "/api/auth/profile",
                    json={
                        "first_name": "Attacker",
                        "is_admin": True,
                        "subscription_tier": "elite",
                        "is_verified": True,
                    },
                    headers={"Authorization": "Bearer fake"},
                )

                assert response.status_code == 422
                auth.update_user.assert_not_awaited()
        finally:
            app.dependency_overrides.clear()

    def test_profile_update_calls_update_user_without_privileged(self):
        from app.core import auth as auth_mod
        from app.main import app

        async def _fake_user():
            return {"id": 42, "user_id": 42, "is_admin": False}

        app.dependency_overrides[auth_mod.get_current_user] = _fake_user
        try:
            with (
                patch("app.main.is_service_available", return_value=True),
                patch("app.main.get_service") as mock_get_service,
            ):
                auth = MagicMock()
                auth.update_user = AsyncMock(
                    return_value={
                        "id": 42,
                        "first_name": "Ben",
                        "is_admin": False,
                        "subscription_tier": "free",
                    }
                )
                mock_get_service.return_value = auth
                client = TestClient(production_app)

                response = client.put(
                    "/api/auth/profile",
                    json={"first_name": "Ben"},
                    headers={"Authorization": "Bearer fake"},
                )

                assert response.status_code == 200
                auth.update_user.assert_awaited()
                args, kwargs = auth.update_user.await_args
                assert args[0] == 42
                assert "is_admin" not in args[1]
                assert kwargs.get("allow_privileged") is False
        finally:
            app.dependency_overrides.clear()


class TestUpdateUserPrivilegeGate:
    def test_non_privileged_update_drops_admin_fields(self):
        svc = AuthServiceDB.__new__(AuthServiceDB)
        user = MagicMock()
        user.id = 7
        user.email = "u@example.com"
        user.username = "user7"
        user.first_name = "A"
        user.last_name = "B"
        user.subscription_tier = "free"
        user.is_verified = False
        user.is_admin = False
        user.is_hidden = False
        user.totp_enabled = False

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = user

        with patch("app.services.auth_service_db.SessionLocal", return_value=db):
            result = asyncio.run(
                svc.update_user(
                    7,
                    {
                        "first_name": "Ok",
                        "is_admin": True,
                        "subscription_tier": "elite",
                        "is_verified": True,
                    },
                    allow_privileged=False,
                )
            )

        assert user.is_admin is False
        assert user.subscription_tier == "free"
        assert user.is_verified is False
        assert user.first_name == "Ok"
        assert result["is_admin"] is False

    def test_privileged_update_allows_admin_fields(self):
        svc = AuthServiceDB.__new__(AuthServiceDB)
        user = MagicMock()
        user.id = 8
        user.email = "admin@example.com"
        user.username = "admin"
        user.first_name = "A"
        user.last_name = "B"
        user.subscription_tier = "free"
        user.is_verified = False
        user.is_admin = False
        user.is_hidden = False
        user.totp_enabled = False

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = user

        with patch("app.services.auth_service_db.SessionLocal", return_value=db):
            result = asyncio.run(
                svc.update_user(
                    8,
                    {"is_admin": True, "subscription_tier": "elite"},
                    allow_privileged=True,
                )
            )

        assert user.is_admin is True
        assert user.subscription_tier == "elite"
        assert result["is_admin"] is True


class TestEmailNameEscaping:
    def test_safe_display_name_escapes_html(self):
        assert "<" not in _safe_display_name("<script>x</script>")
        assert "&lt;script&gt;" in _safe_display_name("<script>x</script>")
        assert _safe_display_name(None) == "there"
        assert _safe_display_name("") == "there"

    @patch.object(EmailService, "send_email", return_value=True)
    def test_verification_email_escapes_first_name(self, mock_send):
        svc = EmailService.__new__(EmailService)
        svc.app_url = "https://yetai.app"
        svc.send_email = mock_send
        svc.send_verification_email(
            "a@b.com", "tok", first_name="<img src=x onerror=alert(1)>"
        )
        html_body = mock_send.call_args[0][2]
        assert "<img" not in html_body
        assert "&lt;img" in html_body


class TestUnauthDebugRoutesGated:
    def test_restart_scheduler_requires_auth(self):
        client = TestClient(production_app)
        response = client.post("/restart-scheduler")
        assert response.status_code in (401, 403)

    def test_migrate_data_requires_auth(self):
        client = TestClient(production_app)
        response = client.post("/api/admin/migrate-data")
        assert response.status_code in (401, 403)

    def test_featured_games_post_requires_auth(self):
        client = TestClient(production_app)
        response = client.post("/api/admin/featured-games", json={"featured_games": []})
        assert response.status_code in (401, 403)
