"""
Auth module with JWT token validation
"""

from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Dict:
    """
    Extract and validate current user from JWT token
    """
    try:
        token = credentials.credentials

        # Import auth service to verify token
        from app.core.service_loader import get_service, is_service_available

        if not is_service_available("auth_service"):
            # Fall back to mock user if auth service unavailable
            logger.warning("Auth service unavailable, using mock user")
            return {
                "user_id": 1,
                "id": 1,
                "email": "demo@example.com",
                "username": "demo_user",
                "is_active": True,
                "subscription_tier": "FREE",
            }

        auth_service = get_service("auth_service")

        # Verify token and get user ID
        user_id = auth_service.verify_token(token)
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        # Get full user data by ID
        user_data = await auth_service.get_user_by_id(user_id)
        if not user_data:
            raise HTTPException(status_code=401, detail="User not found")

        # Add user_id for compatibility
        user_data["user_id"] = user_data["id"]

        return user_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating token: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")


async def require_admin(current_user: Dict = Depends(get_current_user)) -> Dict:
    """Require admin privileges.

    Returns the resolved user record on success, raises 403 otherwise.

    When the auth service is unavailable (local dev / startup races), user_id
    8 is treated as admin so the dev seed admin remains usable.
    """
    from app.core.service_loader import get_service, is_service_available

    if is_service_available("auth_service"):
        auth_service = get_service("auth_service")
        try:
            user_data = await auth_service.get_user_by_id(
                current_user.get("id") or current_user.get("user_id")
            )
            if not user_data or not user_data.get("is_admin", False):
                raise HTTPException(
                    status_code=403, detail="Admin privileges required"
                )
            return user_data
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error checking admin privileges: {e}")
            raise HTTPException(
                status_code=403, detail="Admin privileges required"
            )

    if (current_user.get("id") or current_user.get("user_id")) == 8:
        return current_user
    raise HTTPException(status_code=403, detail="Admin privileges required")
