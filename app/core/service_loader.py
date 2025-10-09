"""
Service loader with graceful degradation for production deployments
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class ServiceAvailability:
    """Track which services are available in the current environment"""

    def __init__(self):
        self.services: Dict[str, bool] = {}
        self.instances: Dict[str, Any] = {}

    def load_service(
        self, name: str, import_path: str, fallback_value: Any = None
    ) -> Any:
        """
        Load a service with graceful error handling

        Args:
            name: Service name for tracking
            import_path: Python import path (e.g., "app.services.auth_service.auth_service")
            fallback_value: Value to return if service loading fails

        Returns:
            Service instance or fallback value
        """
        try:
            # Parse import path
            if "." in import_path:
                module_path, attr_name = import_path.rsplit(".", 1)
            else:
                module_path, attr_name = import_path, None

            # Import module
            import importlib

            module = importlib.import_module(module_path)

            # Get service instance
            if attr_name:
                service = getattr(module, attr_name)
            else:
                service = module

            self.services[name] = True
            self.instances[name] = service
            logger.info(f"✅ {name} service loaded successfully")
            return service

        except Exception as e:
            self.services[name] = False
            self.instances[name] = fallback_value
            logger.warning(f"⚠️  {name} service not available: {e}")
            return fallback_value

    def is_available(self, name: str) -> bool:
        """Check if a service is available"""
        return self.services.get(name, False)

    def get_service(self, name: str) -> Any:
        """Get a loaded service instance"""
        return self.instances.get(name)

    def get_status(self) -> Dict[str, bool]:
        """Get status of all services"""
        return self.services.copy()


# Global service availability tracker
service_loader = ServiceAvailability()


# Load core services with graceful degradation
def initialize_services():
    """Initialize all services with graceful error handling"""

    logger.info("🚀 Initializing services...")

    # Database services - load database functions individually
    try:
        from app.core.database import check_db_connection, init_db, SessionLocal

        service_loader.services["database"] = True
        service_loader.instances["database"] = {
            "check_db_connection": check_db_connection,
            "init_db": init_db,
            "SessionLocal": SessionLocal,
        }
        logger.info("✅ database service loaded successfully")
    except Exception as e:
        service_loader.services["database"] = False
        service_loader.instances["database"] = None
        logger.warning(f"⚠️  database service not available: {e}")

    # Auth service
    service_loader.load_service(
        "auth_service", "app.services.auth_service_db.auth_service_db"
    )

    # Sports pipeline
    service_loader.load_service(
        "sports_pipeline", "app.services.data_pipeline.sports_pipeline"
    )

    # AI chat service
    service_loader.load_service(
        "ai_chat_service", "app.services.ai_chat_service.ai_chat_service"
    )

    # Fantasy services
    service_loader.load_service(
        "fantasy_pipeline", "app.services.fantasy_pipeline.fantasy_pipeline"
    )

    service_loader.load_service(
        "real_fantasy_pipeline",
        "app.services.real_fantasy_pipeline.real_fantasy_pipeline",
    )

    # Betting services
    service_loader.load_service(
        "bet_service", "app.services.bet_service_db.bet_service_db"
    )

    service_loader.load_service(
        "yetai_bets_service", "app.services.yetai_bets_service_db.yetai_bets_service_db"
    )

    # Analytics services
    service_loader.load_service(
        "performance_tracker", "app.services.performance_tracker.performance_tracker"
    )

    service_loader.load_service(
        "betting_analytics_service",
        "app.services.betting_analytics_service.betting_analytics_service",
    )

    # Other services
    service_loader.load_service(
        "cache_service", "app.services.cache_service.cache_service"
    )

    service_loader.load_service(
        "scheduler_service", "app.services.scheduler_service.scheduler_service"
    )

    service_loader.load_service(
        "google_oauth_service", "app.services.google_oauth_service.google_oauth_service"
    )

    # ESPN API service for popular games
    service_loader.load_service(
        "espn_api_service", "app.services.espn_api_service.espn_api_service"
    )

    # Log summary
    available_services = [
        name for name, available in service_loader.get_status().items() if available
    ]
    unavailable_services = [
        name for name, available in service_loader.get_status().items() if not available
    ]

    logger.info(
        f"✅ Services available ({len(available_services)}): {', '.join(available_services)}"
    )
    if unavailable_services:
        logger.info(
            f"⚠️  Services unavailable ({len(unavailable_services)}): {', '.join(unavailable_services)}"
        )

    return service_loader


# Convenience functions for service access
def get_service(name: str) -> Any:
    """Get a service instance"""
    return service_loader.get_service(name)


def is_service_available(name: str) -> bool:
    """Check if a service is available"""
    return service_loader.is_available(name)


def require_service(name: str):
    """Decorator to require a service for an endpoint"""

    def decorator(func):
        def wrapper(*args, **kwargs):
            if not is_service_available(name):
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=503, detail=f"{name} service is currently unavailable"
                )
            return func(*args, **kwargs)

        return wrapper

    return decorator
