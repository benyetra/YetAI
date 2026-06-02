"""
OpenAPI customization for YetAI — agent-ready metadata, split public/admin specs.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.core.config import settings

OPENAPI_TAGS = [
    {
        "name": "health",
        "description": "Liveness and deployment health checks.",
    },
    {
        "name": "auth",
        "description": "Registration, login, OAuth, profile, and JWT session management.",
    },
    {
        "name": "users",
        "description": "User profile, avatar, performance, and preferences.",
    },
    {
        "name": "bets",
        "description": "YetAI picks, parlays, user bets, and verification.",
    },
    {
        "name": "odds",
        "description": "Sportsbook odds and game lines.",
    },
    {
        "name": "predictions",
        "description": "ML prediction tables (PRO/ELITE). Requires Bearer JWT.",
    },
    {
        "name": "fantasy",
        "description": "Fantasy platform connections, leagues, rosters, and recommendations.",
    },
    {
        "name": "fantasy-analytics",
        "description": "Historical NFL fantasy analytics (trends, matchups, waivers).",
    },
    {
        "name": "sleeper",
        "description": "Sleeper account linking and roster/league sync.",
    },
    {
        "name": "subscriptions",
        "description": "Stripe checkout, webhooks, and subscription management.",
    },
    {
        "name": "tools",
        "description": "Betting tools (e.g. Owen's Betting Corner).",
    },
    {
        "name": "admin",
        "description": "Admin-only operations. Requires admin JWT.",
    },
    {
        "name": "webhooks",
        "description": "Inbound webhooks from third parties.",
    },
    {
        "name": "platform",
        "description": "Public platform statistics and status.",
    },
    {
        "name": "debug",
        "description": "Internal debug and test endpoints (non-production use).",
    },
]

PUBLIC_SERVERS = [
    {"url": "https://api.yetai.app", "description": "Production"},
    {"url": "http://localhost:8000", "description": "Local development"},
]

# Paths that do not require Authorization: Bearer
PUBLIC_UNAUTHENTICATED_PATHS: frozenset[str] = frozenset(
    {
        "/",
        "/health",
        "/api/status",
        "/api/platform/stats",
        "/api/odds",
        "/api/auth/register",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/verify-email",
        "/api/auth/resend-verification",
        "/api/auth/forgot-password",
        "/api/auth/reset-password",
        "/api/auth/google/url",
        "/api/auth/google/callback",
        "/api/auth/google/verify",
        "/api/subscription/webhook",
    }
)

ADMIN_PATH_PREFIXES = ("/api/admin",)
DEBUG_PATH_PREFIXES = ("/debug", "/api/test")


def _path_audience(path: str) -> str:
    """Classify a route for spec splitting: public, admin, or debug."""
    if any(path.startswith(p) for p in DEBUG_PATH_PREFIXES):
        return "debug"
    if any(path.startswith(p) for p in ADMIN_PATH_PREFIXES):
        return "admin"
    return "public"


def infer_tag(path: str, existing_tags: list[str] | None) -> str:
    """Map URL prefix to OpenAPI tag when the route has no tag."""
    if existing_tags:
        first = existing_tags[0]
        if first in {t["name"] for t in OPENAPI_TAGS}:
            return first
        if first.startswith("admin"):
            return "admin"
        if first == "sleeper_sync":
            return "sleeper"
        if first == "predictions":
            return "predictions"

    if path in {"/", "/health"}:
        return "health"
    if path.startswith("/api/auth"):
        return "auth"
    if path.startswith("/api/subscription"):
        return "subscriptions"
    if path.startswith("/api/v1/predictions"):
        return "predictions"
    if path.startswith("/api/v1/tools") or path.startswith("/api/admin/owens-bets"):
        return "tools"
    if path.startswith("/api/v1/fantasy/analytics"):
        return "fantasy-analytics"
    if path.startswith("/api/sleeper") or path.startswith("/sleeper"):
        return "sleeper"
    if "/fantasy" in path:
        return "fantasy"
    if path.startswith("/api/odds"):
        return "odds"
    if (
        path.startswith("/api/yetai-bets")
        or path.startswith("/api/bets")
        or "/bets" in path
    ):
        return "bets"
    if path.startswith("/api/live") or "live-bet" in path:
        return "bets"
    if path.startswith("/api/platform") or path.startswith("/api/status"):
        return "platform"
    if path.startswith("/debug") or path.startswith("/api/test"):
        return "debug"
    if path.startswith("/api/admin"):
        return "admin"
    if path.startswith("/api/user"):
        return "users"
    if path.startswith("/api/leaderboard"):
        return "users"
    return "platform"


def make_operation_id(method: str, path: str) -> str:
    """Stable operationId for LLM tool routing (e.g. auth_login_post)."""
    segments = [
        s
        for s in path.strip("/").split("/")
        if s and not (s.startswith("{") and s.endswith("}"))
    ]
    if segments and segments[0] == "api":
        segments = segments[1:]
    slug = "_".join(re.sub(r"[^a-zA-Z0-9_]", "_", s) for s in segments) or "root"
    return f"{slug}_{method.lower()}"


def _needs_bearer(path: str, method: str) -> bool:
    if method.upper() == "OPTIONS":
        return False
    if path in PUBLIC_UNAUTHENTICATED_PATHS:
        return False
    if path.startswith("/debug") or path.startswith("/api/test"):
        return False
    if path.startswith("/api/auth/google/callback"):
        return False
    return path.startswith("/api/") or path.startswith("/api/v1/")


def enhance_openapi_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Add tags, operationIds, security, and shared error responses."""
    schema = copy.deepcopy(schema)
    schema.setdefault("info", {})
    schema["info"].setdefault("contact", {"name": "YetAI", "url": "https://yetai.app"})
    schema["info"]["x-agent-documentation"] = "docs/api/README.md"
    schema["info"]["x-authentication"] = (
        "Obtain a JWT via POST /api/auth/login or /api/auth/register, "
        "then send Authorization: Bearer <token> on protected routes."
    )

    components = schema.setdefault("components", {})
    schemes = components.setdefault("securitySchemes", {})
    bearer_desc = "JWT access token from /api/auth/login or /api/auth/register."
    schemes["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": bearer_desc,
    }
    if "HTTPBearer" in schemes:
        schemes.pop("HTTPBearer", None)
    error_ref = "#/components/schemas/ErrorResponse"
    if "ErrorResponse" not in components.get("schemas", {}):
        components.setdefault("schemas", {})["ErrorResponse"] = {
            "type": "object",
            "required": ["detail"],
            "properties": {
                "detail": {"type": "string"},
                "code": {"type": "string", "nullable": True},
                "retry_after": {"type": "integer", "nullable": True},
                "context": {"type": "object", "nullable": True},
            },
        }

    standard_errors = {
        "401": {
            "description": "Missing or invalid JWT",
            "content": {
                "application/json": {
                    "schema": {"$ref": error_ref},
                    "example": {"detail": "Invalid or expired token"},
                }
            },
        },
        "403": {
            "description": "Forbidden — insufficient role or subscription tier",
            "content": {
                "application/json": {
                    "schema": {"$ref": error_ref},
                    "example": {"detail": "Admin privileges required"},
                }
            },
        },
        "503": {
            "description": "Required backend service unavailable",
            "content": {
                "application/json": {
                    "schema": {"$ref": error_ref},
                    "example": {"detail": "Service is currently unavailable"},
                }
            },
        },
    }

    paths = schema.get("paths", {})
    for path, path_item in paths.items():
        audience = _path_audience(path)
        for method, operation in path_item.items():
            if method in ("parameters", "servers", "summary", "description"):
                continue
            if not isinstance(operation, dict):
                continue

            operation.setdefault("tags", [infer_tag(path, operation.get("tags"))])
            if not operation.get("operationId"):
                operation["operationId"] = make_operation_id(method, path)

            if not operation.get("summary") and operation.get("description"):
                operation["summary"] = (
                    operation["description"].split("\n")[0].strip()[:120]
                )

            operation["x-audience"] = audience

            if _needs_bearer(path, method):
                if "security" not in operation:
                    operation["security"] = [{"BearerAuth": []}]
                else:
                    operation["security"] = [
                        {"BearerAuth": []} if "HTTPBearer" in sec else sec
                        for sec in operation["security"]
                    ]

            responses = operation.setdefault("responses", {})
            for code, body in standard_errors.items():
                if code not in responses and _needs_bearer(path, method):
                    responses[code] = body

    schema["tags"] = OPENAPI_TAGS
    return schema


def filter_schema_by_audience(
    schema: dict[str, Any], *, audiences: frozenset[str]
) -> dict[str, Any]:
    """Build a subset OpenAPI document for the given path audiences."""
    out = copy.deepcopy(schema)
    filtered_paths: dict[str, Any] = {}
    for path, path_item in schema.get("paths", {}).items():
        if _path_audience(path) in audiences:
            filtered_paths[path] = path_item
    out["paths"] = filtered_paths
    is_admin = audiences <= frozenset({"admin", "debug"})
    title_suffix = "Admin" if is_admin else "Public"
    out["info"] = {
        **out.get("info", {}),
        "title": f"YetAI API ({title_suffix})",
        "description": (
            "Admin and internal endpoints for YetAI operators."
            if is_admin
            else "Consumer-facing YetAI API for apps and AI agents."
        ),
    }
    if not is_admin:
        out["servers"] = PUBLIC_SERVERS
    return out


def build_openapi_schema(app: FastAPI) -> dict[str, Any]:
    """Generate full enhanced OpenAPI schema for the app."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema = enhance_openapi_schema(schema)
    app.openapi_schema = schema
    return schema


def configure_openapi(app: FastAPI) -> None:
    """Attach custom OpenAPI generator and tag metadata to the FastAPI app."""

    def custom_openapi() -> dict[str, Any]:
        return build_openapi_schema(app)

    app.openapi = custom_openapi  # type: ignore[method-assign]


def export_openapi_variants(app: FastAPI) -> dict[str, dict[str, Any]]:
    """Return full, public, and admin OpenAPI dicts for serialization."""
    app.openapi_schema = None
    full = build_openapi_schema(app)
    return {
        "full": full,
        "public": filter_schema_by_audience(full, audiences=frozenset({"public"})),
        "admin": filter_schema_by_audience(
            full, audiences=frozenset({"admin", "debug"})
        ),
    }
