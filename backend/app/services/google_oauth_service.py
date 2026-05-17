import hashlib
import hmac
import os
import secrets
import time
from typing import Dict, Optional

import google.auth.transport.requests
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow

from app.core.config import settings

# State tokens are valid for 10 minutes
_STATE_TTL = 600


def _sign_state(nonce: str, ts: int) -> str:
    key = settings.SECRET_KEY.encode()
    msg = f"{nonce}:{ts}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def _make_state() -> str:
    nonce = secrets.token_urlsafe(24)
    ts = int(time.time())
    sig = _sign_state(nonce, ts)
    return f"{nonce}.{ts}.{sig}"


def _verify_state(state: str) -> bool:
    """Return True if state is a valid, unexpired HMAC-signed token."""
    try:
        nonce, ts_str, sig = state.rsplit(".", 2)
        ts = int(ts_str)
        if int(time.time()) - ts > _STATE_TTL:
            return False
        expected = _sign_state(nonce, ts)
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


class GoogleOAuthService:
    def __init__(self):
        self.client_id = settings.GOOGLE_CLIENT_ID or "your-google-client-id"
        self.client_secret = (
            settings.GOOGLE_CLIENT_SECRET or "your-google-client-secret"
        )
        self.redirect_uri = settings.get_google_redirect_uri()

        self.scopes = [
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
        ]

    def get_authorization_url(self) -> Dict[str, str]:
        """Generate Google OAuth authorization URL"""
        try:
            flow = Flow.from_client_config(
                {
                    "web": {
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": [self.redirect_uri],
                    }
                },
                scopes=self.scopes,
            )
            flow.redirect_uri = self.redirect_uri

            state = _make_state()
            authorization_url, _ = flow.authorization_url(
                access_type="offline", include_granted_scopes="true", state=state
            )

            return {"authorization_url": authorization_url, "state": state}

        except Exception as e:
            print(f"Error generating authorization URL: {e}")
            return {"error": "Failed to generate authorization URL"}

    def handle_callback(self, code: str, state: str) -> Dict:
        """Handle OAuth callback and extract user info"""
        try:
            if not _verify_state(state):
                return {"error": "Invalid state token"}

            # Create flow instance
            flow = Flow.from_client_config(
                {
                    "web": {
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": [self.redirect_uri],
                    }
                },
                scopes=self.scopes,
            )
            flow.redirect_uri = self.redirect_uri

            # Exchange authorization code for tokens
            flow.fetch_token(code=code)

            # Get user info from ID token
            credentials = flow.credentials
            request = google.auth.transport.requests.Request()

            # Verify and decode ID token
            id_info = id_token.verify_oauth2_token(
                credentials.id_token, request, self.client_id
            )

            return {
                "success": True,
                "user_info": {
                    "google_id": id_info.get("sub"),
                    "email": id_info.get("email"),
                    "email_verified": id_info.get("email_verified", False),
                    "first_name": id_info.get("given_name", ""),
                    "last_name": id_info.get("family_name", ""),
                    "picture": id_info.get("picture", ""),
                    "name": id_info.get("name", ""),
                },
            }

        except Exception as e:
            print(f"Error handling OAuth callback: {e}")
            return {"error": f"OAuth callback failed: {str(e)}"}

    def verify_id_token(self, token: str) -> Optional[Dict]:
        """Verify Google ID token (for frontend-only OAuth)"""
        try:
            request = google.auth.transport.requests.Request()
            id_info = id_token.verify_oauth2_token(token, request, self.client_id)

            return {
                "google_id": id_info.get("sub"),
                "email": id_info.get("email"),
                "email_verified": id_info.get("email_verified", False),
                "first_name": id_info.get("given_name", ""),
                "last_name": id_info.get("family_name", ""),
                "picture": id_info.get("picture", ""),
                "name": id_info.get("name", ""),
            }

        except Exception as e:
            print(f"Error verifying ID token: {e}")
            return None


# Global instance
try:
    google_oauth_service = GoogleOAuthService()
    print(f"✓ Google OAuth service initialized successfully")
    print(
        f"  - Client ID: {google_oauth_service.client_id[:20]}..."
        if google_oauth_service.client_id
        else "  - Client ID: NOT SET"
    )
    print(f"  - Redirect URI: {google_oauth_service.redirect_uri}")
except Exception as e:
    print(f"✗ Failed to initialize Google OAuth service: {e}")
    import traceback

    traceback.print_exc()
    google_oauth_service = None
