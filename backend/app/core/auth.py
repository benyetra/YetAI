"""
Temporary auth module - TODO: Implement proper authentication
"""


def get_current_user():
    """
    Temporary function that returns a mock user
    TODO: Implement proper JWT authentication
    """
    return {
        "id": 1,
        "email": "demo@example.com",
        "username": "demo_user",
        "is_active": True,
        "subscription_tier": "FREE",
    }
