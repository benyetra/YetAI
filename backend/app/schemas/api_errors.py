"""Shared API error shapes for OpenAPI documentation."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Standard HTTP error body returned by most YetAI endpoints."""

    detail: str = Field(..., description="Human-readable error message.")
    code: Optional[str] = Field(
        default=None,
        description="Optional machine-readable error code when provided.",
    )
    retry_after: Optional[int] = Field(
        default=None,
        description="Seconds to wait before retrying (rate limits, lockouts).",
    )
    context: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional structured context for debugging.",
    )
