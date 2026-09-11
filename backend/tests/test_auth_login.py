"""Login endpoint validation and credential lookup."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app as production_app
from app.services.auth_service_db import AuthServiceDB


class TestLoginEndpoint:
    @patch("app.main.is_service_available", return_value=True)
    @patch("app.main.get_service")
    def test_login_success(self, mock_get_service, _available):
        auth = MagicMock()
        auth.authenticate_user = AsyncMock(
            return_value={
                "success": True,
                "access_token": "tok",
                "user": {"id": 1, "email": "ben@yetai.app"},
            }
        )
        mock_get_service.return_value = auth
        client = TestClient(production_app)

        response = client.post(
            "/api/auth/login",
            json={"email_or_username": "  Ben@YetAI.app  ", "password": "secret"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "success"
        auth.authenticate_user.assert_awaited_once_with(
            email_or_username="Ben@YetAI.app",
            password="secret",
        )

    def test_login_rejects_empty_password(self):
        client = TestClient(production_app)
        response = client.post(
            "/api/auth/login",
            json={"email_or_username": "a@example.com", "password": ""},
        )
        assert response.status_code == 422

    def test_login_rejects_whitespace_identifier(self):
        client = TestClient(production_app)
        response = client.post(
            "/api/auth/login",
            json={"email_or_username": "   ", "password": "secret"},
        )
        assert response.status_code == 422


class TestAuthServicePasswordSet:
    def test_google_only_accounts_get_explicit_error(self):
        err = AuthServiceDB._google_only_password_error()
        assert err["success"] is False
        assert "Google Sign-In" in err["error"]
        assert "Forgot password" in err["error"]

    def test_invalid_credentials_mentions_google_path(self):
        err = AuthServiceDB._invalid_credentials_error()
        assert "Google" in err["error"]
        assert "Forgot password" in err["error"]

    def test_verify_password_rejects_empty_hash(self):
        svc = AuthServiceDB.__new__(AuthServiceDB)
        assert svc.verify_password("secret", "") is False
        assert svc.verify_password("secret", None) is False  # type: ignore[arg-type]

    @patch("app.services.auth_service_db.SessionLocal")
    def test_authenticate_user_blocks_unset_password(self, mock_session_local):
        import asyncio

        user = MagicMock()
        user.password_set = False
        user.is_active = True
        user.password_hash = "unused"

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = user
        mock_session_local.return_value = db

        svc = AuthServiceDB.__new__(AuthServiceDB)
        result = asyncio.get_event_loop().run_until_complete(
            svc.authenticate_user("user@example.com", "anything")
        )
        assert result["success"] is False
        assert "Google Sign-In" in result["error"]
        db.close.assert_called_once()
