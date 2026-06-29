import os
from typing import List, Optional

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Template values from .env.example / .env.production — must never be sent to Odds API.
_ODDS_API_KEY_PLACEHOLDERS = frozenset(
    {
        "your_odds_api_key_here",
        "your-odds-api-key",
        "your-odds-api-key-here",
    }
)


def _clean_odds_api_key(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    if not isinstance(raw, str):
        return raw
    cleaned = raw.strip().strip('"').strip("'")
    if not cleaned or cleaned in _ODDS_API_KEY_PLACEHOLDERS:
        return None
    return cleaned


def _resolve_odds_api_key(
    field_value: Optional[str] = None,
) -> tuple[Optional[str], str]:
    """Return (key, source_label) using the same precedence as Settings."""
    env_primary = _clean_odds_api_key(os.environ.get("ODDS_API_KEY"))
    if env_primary:
        return env_primary, "ODDS_API_KEY"
    field_key = _clean_odds_api_key(field_value)
    if field_key:
        return field_key, "settings_field"
    for env_name in ("ODDS_API", "THE_ODDS_API_KEY"):
        alias_key = _clean_odds_api_key(os.environ.get(env_name))
        if alias_key:
            return alias_key, env_name
    return None, "none"


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

    # Odds API: bind only ODDS_API_KEY here. ODDS_API is a manual fallback in
    # _coalesce_odds_api_key so a stale ODDS_API placeholder cannot override a
    # valid ODDS_API_KEY on Railway.
    ODDS_API_KEY: Optional[str] = Field(default=None, validation_alias="ODDS_API_KEY")
    OPENAI_API_KEY: Optional[str] = None
    WEATHER_API_KEY: Optional[str] = None

    # YetiWatch (WNBA news synthesis via Bedrock; heuristic fallback when disabled)
    YETIWATCH_BEDROCK_ENABLED: bool = False
    YETIWATCH_BEDROCK_MODEL_ID: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    YETIWATCH_BEDROCK_REGION: str = "us-east-1"

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
        return _clean_odds_api_key(value)

    @model_validator(mode="after")
    def _coalesce_odds_api_key(self) -> "Settings":
        """Resolve Odds API key from process env with explicit precedence.

        1. ``ODDS_API_KEY`` env (Railway canonical name) — always wins when valid.
        2. Field value from pydantic (e.g. local ``.env``) if not a placeholder.
        3. ``ODDS_API`` / ``THE_ODDS_API_KEY`` env aliases when (1) missing.
        """
        key, _source = _resolve_odds_api_key(self.ODDS_API_KEY)
        object.__setattr__(self, "ODDS_API_KEY", key)
        return self

    def odds_api_env_diagnostics(self) -> dict:
        """Non-secret hints for debugging env wiring (Railway vs Vercel)."""
        env_key_raw = os.environ.get("ODDS_API_KEY") or ""
        env_alias_raw = os.environ.get("ODDS_API") or ""
        key, resolved_from = _resolve_odds_api_key(self.ODDS_API_KEY)
        env_primary = _clean_odds_api_key(env_key_raw)
        env_alias = _clean_odds_api_key(env_alias_raw)
        return {
            "resolved_key_configured": bool(key),
            "resolved_from": resolved_from,
            "env_ODDS_API_KEY_set": bool(env_key_raw.strip()),
            "env_ODDS_API_set": bool(env_alias_raw.strip()),
            "env_ODDS_API_KEY_usable": bool(env_primary),
            "env_ODDS_API_usable": bool(env_alias),
            "env_ODDS_API_KEY_placeholder": bool(
                env_key_raw.strip() and not env_primary
            ),
            "env_ODDS_API_placeholder": bool(env_alias_raw.strip() and not env_alias),
            "resolved_key_length": len(key) if key else 0,
            "resolved_key_preview": (
                f"{key[:4]}...{key[-4:]}" if key and len(key) >= 8 else "too_short"
            ),
        }

    @model_validator(mode="after")
    def disable_debug_in_production(self) -> "Settings":
        """Production must not run SQL echo / verbose dev defaults (Railway log floods)."""
        if self.ENVIRONMENT == "production":
            object.__setattr__(self, "DEBUG", False)
        return self

    @model_validator(mode="after")
    def prefer_public_database_url(self) -> "Settings":
        """Local dev: use DATABASE_PUBLIC_URL when DATABASE_URL is Railway-internal."""
        public = os.environ.get("DATABASE_PUBLIC_URL", "").strip()
        if public and "railway.internal" in (self.DATABASE_URL or ""):
            return self.model_copy(update={"DATABASE_URL": public})
        return self


settings = Settings()


def get_odds_api_key() -> Optional[str]:
    """Resolve Odds API key at call time (Railway env may update without reload)."""
    key, _source = _resolve_odds_api_key(settings.ODDS_API_KEY)
    return key
