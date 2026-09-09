"""Login endpoint validation and credential lookup."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app as production_app


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
