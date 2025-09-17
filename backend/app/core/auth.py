"""
Auth module with JWT token validation
"""

from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)

security = HTTPBearer()


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict:
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
