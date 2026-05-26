import os
from typing import List, Optional

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )
    # App
    APP_NAME: str = "AI Sports Betting MVP"
    DEBUG: bool = True
    ENVIRONMENT: str = "development"  # development, staging, production

    # Database
    DATABASE_URL: str = (
        "postgresql://sports_user:sports_pass@localhost:5432/sports_betting_ai"
    )

    # External APIs — accept ODDS_API_KEY or ODDS_API (common Railway/Vercel typo)
    ODDS_API_KEY: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("ODDS_API_KEY", "ODDS_API"),
    )
    OPENAI_API_KEY: Optional[str] = None
    WEATHER_API_KEY: Optional[str] = None

    # Authentication
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=720,  # 12 hours
        validation_alias=AliasChoices(
            "ACCESS_TOKEN_EXPIRE_MINUTES",
            "JWT_ACCESS_TOKEN_EXPIRES",
        ),
    )

    # Redis / Celery broker (Railway: use plugin reference on API + celery-worker)
    REDIS_URL: str = Field(
        default="redis://localhost:6379",
        validation_alias=AliasChoices(
            "REDIS_URL",
            "REDIS_PRIVATE_URL",
            "REDIS_PUBLIC_URL",
            "CELERY_BROKER_URL",
        ),
    )

    # External Services
    STRIPE_SECRET_KEY: Optional[str] = None
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None

    # Google OAuth
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: Optional[str] = None

    # Frontend URLs for CORS (can be set via environment variables)
    FRONTEND_URL: Optional[str] = None
    ALLOWED_ORIGINS: Optional[str] = None  # Comma-separated list

    def get_frontend_urls(self) -> List[str]:
        """Get frontend URLs based on environment and configuration"""
        urls = []

        # Add explicitly configured origins
        if self.ALLOWED_ORIGINS:
            urls.extend([url.strip() for url in self.ALLOWED_ORIGINS.split(",")])

        # Always include production domains
        urls.extend(["https://yetai.app", "https://www.yetai.app"])

        # Add environment-specific defaults
        if self.ENVIRONMENT == "production":
            if self.FRONTEND_URL:
                urls.append(self.FRONTEND_URL)
        elif self.ENVIRONMENT == "staging":
            urls.extend(["https://staging.yetai.app"])
            if self.FRONTEND_URL:
                urls.append(self.FRONTEND_URL)
        else:  # development
            urls.extend(
                [
                    "http://localhost:3000",
                    "http://localhost:3001",
                    "http://localhost:3002",
                    "http://localhost:3003",
                    "http://127.0.0.1:3000",
                    "http://127.0.0.1:3001",
                    "http://127.0.0.1:3002",
                    "http://127.0.0.1:3003",
                ]
            )

        # Remove duplicates while preserving order
        return list(dict.fromkeys(urls))

    def get_google_redirect_uri(self) -> str:
        """Get Google OAuth redirect URI based on environment"""
        if self.GOOGLE_REDIRECT_URI:
            return self.GOOGLE_REDIRECT_URI

        if self.ENVIRONMENT == "production":
            return "https://api.yetai.app/api/auth/google/callback"
        elif self.ENVIRONMENT == "staging":
            return "https://staging-api.yetai.app/api/auth/google/callback"
        else:  # development
            return "http://localhost:8001/api/auth/google/callback"

    @field_validator("ODDS_API_KEY", mode="before")
    @classmethod
    def _normalize_odds_api_key(cls, value: Optional[str]) -> Optional[str]:
        """Strip dashboard copy/paste artifacts (quotes, whitespace)."""
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        cleaned = value.strip().strip('"').strip("'")
        if not cleaned or cleaned == "your_odds_api_key_here":
            return None
        return cleaned

    @model_validator(mode="after")
    def _coalesce_odds_api_key(self) -> "Settings":
        """Read ODDS_API_KEY directly from os.environ as a safety net in case
        pydantic-settings fails to resolve it via AliasChoices, then fall back
        to alternate env var names used by some dashboards."""
        if not self.ODDS_API_KEY:
            raw = (
                os.environ.get("ODDS_API_KEY")
                or os.environ.get("ODDS_API")
                or os.environ.get("THE_ODDS_API_KEY")
            )
            if raw:
                cleaned = raw.strip().strip('"').strip("'")
                if cleaned and cleaned not in (
                    "your_odds_api_key_here",
                    "your-odds-api-key",
                ):
                    self.ODDS_API_KEY = cleaned
        return self

    def odds_api_env_diagnostics(self) -> dict:
        """Non-secret hints for debugging env wiring (Railway vs Vercel)."""
        raw = os.environ.get("ODDS_API_KEY") or os.environ.get("ODDS_API") or ""
        key = self.ODDS_API_KEY or ""
        return {
            "resolved_key_configured": bool(key),
            "env_ODDS_API_KEY_set": bool(os.environ.get("ODDS_API_KEY")),
            "env_ODDS_API_set": bool(os.environ.get("ODDS_API")),
            "raw_env_length": len(raw),
            "resolved_key_length": len(key),
            "resolved_key_preview": (
                f"{key[:4]}...{key[-4:]}" if len(key) >= 8 else "too_short"
            ),
        }

    @model_validator(mode="after")
    def prefer_public_database_url(self) -> "Settings":
        """Local dev: use DATABASE_PUBLIC_URL when DATABASE_URL is Railway-internal."""
        public = os.environ.get("DATABASE_PUBLIC_URL", "").strip()
        if public and "railway.internal" in (self.DATABASE_URL or ""):
            return self.model_copy(update={"DATABASE_URL": public})
        return self


settings = Settings()
