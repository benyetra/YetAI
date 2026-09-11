"""Login endpoint validation and credential lookup."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app as production_app
from app.services.auth_service_db import AuthServiceDB

# Deliberately non-credential-looking fixture plaintext for unit tests only.
_FIXTURE_PW = "fixture-login-value"
_MOCK_HASH_OK = "mock-hash-ok"
_MOCK_HASH_BAD = "mock-hash-bad"


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
            json={
                "email_or_username": "  Ben@YetAI.app  ",
                "password": _FIXTURE_PW,
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "success"
        auth.authenticate_user.assert_awaited_once_with(
            email_or_username="Ben@YetAI.app",
            password=_FIXTURE_PW,
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
            json={"email_or_username": "   ", "password": _FIXTURE_PW},
        )
        assert response.status_code == 422


def _mock_db_with_users(users):
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
        users
    )
    return db


class TestAuthServicePasswordSet:
    def test_google_only_accounts_get_explicit_error(self):
        err = AuthServiceDB._google_only_password_error()
        assert err["success"] is False
        assert "Google Sign-In" in err["error"]
        assert "Forgot password" in err["error"]

    def test_invalid_credentials_is_generic(self):
        err = AuthServiceDB._invalid_credentials_error()
        assert err["error"] == "Invalid email/username or password"
        assert "Google" not in err["error"]

    def test_verify_password_rejects_empty_hash(self):
        svc = AuthServiceDB.__new__(AuthServiceDB)
        assert svc.verify_password(_FIXTURE_PW, "") is False
        assert svc.verify_password(_FIXTURE_PW, None) is False  # type: ignore[arg-type]

    @patch("app.services.auth_service_db.SessionLocal")
    def test_authenticate_user_blocks_unset_password(self, mock_session_local):
        user = MagicMock()
        user.id = 1
        user.password_set = False
        user.is_active = True
        user.password_hash = _MOCK_HASH_BAD

        mock_session_local.return_value = _mock_db_with_users([user])

        svc = AuthServiceDB.__new__(AuthServiceDB)
        result = asyncio.get_event_loop().run_until_complete(
            svc.authenticate_user("user@example.com", _FIXTURE_PW)
        )
        assert result["success"] is False
        assert "Google Sign-In" in result["error"]

    @patch("app.services.auth_service_db.SessionLocal")
    def test_authenticate_prefers_password_match_among_case_duplicates(
        self, mock_session_local
    ):
        """Case-variant Google duplicate must not shadow the password account."""
        google_dup = MagicMock()
        google_dup.id = 10
        google_dup.email = "ben@yetai.app"
        google_dup.username = "ben_google"
        google_dup.password_set = True  # pre-migration Google rows default true
        google_dup.is_active = True
        google_dup.password_hash = _MOCK_HASH_BAD
        google_dup.first_name = "G"
        google_dup.last_name = ""
        google_dup.subscription_tier = "free"
        google_dup.is_verified = True
        google_dup.is_admin = False
        google_dup.avatar_url = None
        google_dup.avatar_thumbnail = None
        google_dup.last_login = None

        password_acct = MagicMock()
        password_acct.id = 2
        password_acct.email = "Ben@YetAI.app"
        password_acct.username = "ben"
        password_acct.password_set = True
        password_acct.is_active = True
        password_acct.password_hash = _MOCK_HASH_OK
        password_acct.first_name = "Ben"
        password_acct.last_name = "Y"
        password_acct.subscription_tier = "pro"
        password_acct.is_verified = True
        password_acct.is_admin = True
        password_acct.avatar_url = None
        password_acct.avatar_thumbnail = None
        password_acct.last_login = None

        # Older Google-ish row first (as unstable .first() might pick)
        mock_session_local.return_value = _mock_db_with_users(
            [google_dup, password_acct]
        )

        svc = AuthServiceDB.__new__(AuthServiceDB)
        svc.verify_password = MagicMock(
            side_effect=lambda plain, hashed: hashed == _MOCK_HASH_OK
        )
        svc.generate_token = MagicMock(return_value="tok")

        result = asyncio.get_event_loop().run_until_complete(
            svc.authenticate_user("ben@yetai.app", _FIXTURE_PW)
        )
        assert result["success"] is True
        assert result["user"]["id"] == 2
        assert result["access_token"] == "tok"
        svc.generate_token.assert_called_once_with(2)
