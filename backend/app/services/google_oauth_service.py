import os
import secrets
from typing import Dict, Optional
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow
import google.auth.transport.requests
from app.core.config import settings


class GoogleOAuthService:
    def __init__(self):
        # Use centralized settings
        self.client_id = settings.GOOGLE_CLIENT_ID or "your-google-client-id"
        self.client_secret = (
            settings.GOOGLE_CLIENT_SECRET or "your-google-client-secret"
        )
        self.redirect_uri = settings.get_google_redirect_uri()

        # OAuth 2.0 scopes - use full URLs for consistency
        self.scopes = [
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
        ]

        # In-memory storage for state tokens (use Redis in production)
        self.state_storage = {}

    def get_authorization_url(self) -> Dict[str, str]:
        """Generate Google OAuth authorization URL"""
        try:
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

            # Generate state for CSRF protection
            state = secrets.token_urlsafe(32)

            # Get authorization URL
            authorization_url, _ = flow.authorization_url(
                access_type="offline", include_granted_scopes="true", state=state
            )

            # Store state (use Redis or database in production)
            self.state_storage[state] = True

            return {"authorization_url": authorization_url, "state": state}

        except Exception as e:
            print(f"Error generating authorization URL: {e}")
            return {"error": "Failed to generate authorization URL"}

    def handle_callback(self, code: str, state: str) -> Dict:
        """Handle OAuth callback and extract user info"""
        try:
            # Verify state token
            if state not in self.state_storage:
                return {"error": "Invalid state token"}

            # Remove used state token
            del self.state_storage[state]

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
