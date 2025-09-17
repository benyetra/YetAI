from pydantic_settings import BaseSettings
from typing import Optional, List


class Settings(BaseSettings):
    # App
    APP_NAME: str = "AI Sports Betting MVP"
    DEBUG: bool = True
    ENVIRONMENT: str = "development"  # development, staging, production

    # Database
    DATABASE_URL: str = (
        "postgresql://sports_user:sports_pass@localhost:5432/sports_betting_ai"
    )

    # External APIs
    ODDS_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    WEATHER_API_KEY: Optional[str] = None

    # Authentication
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

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

        # Add environment-specific defaults
        if self.ENVIRONMENT == "production":
            urls.extend(["https://yetai.app", "https://www.yetai.app"])
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
            return "https://backend-production-f7af.up.railway.app/api/auth/google/callback"
        elif self.ENVIRONMENT == "staging":
            return "https://staging-backend.up.railway.app/api/auth/google/callback"
        else:  # development
            return "http://localhost:8000/api/auth/google/callback"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
