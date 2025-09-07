"""
Cache Service for storing and retrieving API responses.

This service provides caching functionality for The Odds API responses
to reduce API calls and improve response times.
"""

import json
import asyncio
import hashlib
from typing import Optional, Dict, Any, Union
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class InMemoryCache:
    """
    Simple in-memory cache implementation.
    Fallback when Redis is not available.
    """
    
    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cleanup_task = None
        self._start_cleanup_task()
    
    def _start_cleanup_task(self):
        """Start background task to clean up expired entries"""
        if not self._cleanup_task:
            self._cleanup_task = asyncio.create_task(self._cleanup_expired())
    
    async def _cleanup_expired(self):
        """Remove expired entries every 5 minutes"""
        while True:
            try:
                await asyncio.sleep(300)  # 5 minutes
                now = datetime.utcnow()
                expired_keys = []
                
                for key, entry in self._cache.items():
                    if entry["expires_at"] < now:
                        expired_keys.append(key)
                
                for key in expired_keys:
                    del self._cache[key]
                
                if expired_keys:
                    logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")
                    
            except Exception as e:
                logger.error(f"Error during cache cleanup: {e}")
    
    async def get(self, key: str) -> Optional[str]:
        """Get value from cache"""
        if key not in self._cache:
            return None
        
        entry = self._cache[key]
        if entry["expires_at"] < datetime.utcnow():
            del self._cache[key]
            return None
        
        return entry["value"]
    
    async def set(self, key: str, value: str, expire_seconds: int = 300):
        """Set value in cache with expiration"""
        expires_at = datetime.utcnow() + timedelta(seconds=expire_seconds)
        self._cache[key] = {
            "value": value,
            "expires_at": expires_at,
            "created_at": datetime.utcnow()
        }
    
    async def delete(self, key: str):
        """Delete key from cache"""
        if key in self._cache:
            del self._cache[key]
    
    async def clear(self):
        """Clear all cache entries"""
        self._cache.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        now = datetime.utcnow()
        active_entries = 0
        expired_entries = 0
        
        for entry in self._cache.values():
            if entry["expires_at"] > now:
                active_entries += 1
            else:
                expired_entries += 1
        
        return {
            "total_entries": len(self._cache),
            "active_entries": active_entries,
            "expired_entries": expired_entries,
            "cache_type": "in_memory"
        }

class CacheService:
    """
    Main cache service that can use Redis or fall back to in-memory caching.
    """
    
    def __init__(self):
        self._redis_client = None
        self._memory_cache = InMemoryCache()
        self._redis_available = False
        self._initialize_redis()
    
    def _initialize_redis(self):
        """Try to initialize Redis connection"""
        try:
            import redis.asyncio as redis
            from ..core.config import settings
            
            self._redis_client = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True
            )
            self._redis_available = True
            logger.info("Redis cache initialized successfully")
            
        except ImportError:
            logger.warning("Redis not available, using in-memory cache")
            self._redis_available = False
        except Exception as e:
            logger.warning(f"Failed to initialize Redis, using in-memory cache: {e}")
            self._redis_available = False
    
    async def _test_redis_connection(self) -> bool:
        """Test if Redis is available"""
        if not self._redis_available or not self._redis_client:
            return False
        
        try:
            await self._redis_client.ping()
            return True
        except Exception as e:
            logger.warning(f"Redis connection test failed: {e}")
            self._redis_available = False
            return False
    
    def _generate_cache_key(self, prefix: str, **kwargs) -> str:
        """Generate a consistent cache key from parameters"""
        # Create a string from sorted parameters
        param_str = "&".join(f"{k}={v}" for k, v in sorted(kwargs.items()) if v is not None)
        
        # Hash the parameters to keep key length reasonable
        param_hash = hashlib.md5(param_str.encode()).hexdigest()[:16]
        
        return f"odds_api:{prefix}:{param_hash}"
    
    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get cached data"""
        try:
            # Try Redis first
            if self._redis_available and await self._test_redis_connection():
                try:
                    cached_data = await self._redis_client.get(key)
                    if cached_data:
                        return json.loads(cached_data)
                except Exception as e:
                    logger.warning(f"Redis get failed, falling back to memory: {e}")
            
            # Fall back to in-memory cache
            cached_data = await self._memory_cache.get(key)
            if cached_data:
                return json.loads(cached_data)
            
            return None
            
        except Exception as e:
            logger.error(f"Cache get error for key {key}: {e}")
            return None
    
    async def set(self, key: str, data: Dict[str, Any], expire_seconds: int = 300):
        """Set cached data with expiration"""
        try:
            serialized_data = json.dumps(data, default=str)
            
            # Try Redis first
            if self._redis_available and await self._test_redis_connection():
                try:
                    await self._redis_client.setex(key, expire_seconds, serialized_data)
                    return
                except Exception as e:
                    logger.warning(f"Redis set failed, falling back to memory: {e}")
            
            # Fall back to in-memory cache
            await self._memory_cache.set(key, serialized_data, expire_seconds)
            
        except Exception as e:
            logger.error(f"Cache set error for key {key}: {e}")
    
    async def delete(self, key: str):
        """Delete cached data"""
        try:
            # Try Redis first
            if self._redis_available and await self._test_redis_connection():
                try:
                    await self._redis_client.delete(key)
                except Exception as e:
                    logger.warning(f"Redis delete failed: {e}")
            
            # Also delete from memory cache
            await self._memory_cache.delete(key)
            
        except Exception as e:
            logger.error(f"Cache delete error for key {key}: {e}")
    
    async def clear_pattern(self, pattern: str):
        """Clear all keys matching a pattern"""
        try:
            if self._redis_available and await self._test_redis_connection():
                try:
                    keys = await self._redis_client.keys(pattern)
                    if keys:
                        await self._redis_client.delete(*keys)
                        logger.info(f"Cleared {len(keys)} Redis keys matching pattern: {pattern}")
                except Exception as e:
                    logger.warning(f"Redis pattern clear failed: {e}")
            
            # For in-memory cache, we'd need to implement pattern matching
            # For simplicity, just clear all if it's a wildcard pattern
            if pattern.endswith("*"):
                await self._memory_cache.clear()
                logger.info("Cleared all in-memory cache entries")
                
        except Exception as e:
            logger.error(f"Cache pattern clear error for pattern {pattern}: {e}")
    
    # Convenience methods for specific data types
    
    async def get_sports_list(self) -> Optional[Dict[str, Any]]:
        """Get cached sports list"""
        key = self._generate_cache_key("sports_list")
        return await self.get(key)
    
    async def set_sports_list(self, data: Dict[str, Any], expire_seconds: int = 3600):
        """Cache sports list (expires in 1 hour)"""
        key = self._generate_cache_key("sports_list")
        await self.set(key, data, expire_seconds)
    
    async def get_odds(self, sport_key: str, regions: str, markets: str, 
                       odds_format: str, bookmakers: str = None) -> Optional[Dict[str, Any]]:
        """Get cached odds data"""
        key = self._generate_cache_key(
            "odds",
            sport_key=sport_key,
            regions=regions,
            markets=markets,
            odds_format=odds_format,
            bookmakers=bookmakers
        )
        return await self.get(key)
    
    async def set_odds(self, sport_key: str, regions: str, markets: str, 
                       odds_format: str, data: Dict[str, Any], 
                       bookmakers: str = None, expire_seconds: int = 300):
        """Cache odds data (expires in 5 minutes)"""
        key = self._generate_cache_key(
            "odds",
            sport_key=sport_key,
            regions=regions,
            markets=markets,
            odds_format=odds_format,
            bookmakers=bookmakers
        )
        await self.set(key, data, expire_seconds)
    
    async def get_scores(self, sport_key: str, days_from: int) -> Optional[Dict[str, Any]]:
        """Get cached scores data"""
        key = self._generate_cache_key("scores", sport_key=sport_key, days_from=days_from)
        return await self.get(key)
    
    async def set_scores(self, sport_key: str, days_from: int, data: Dict[str, Any], 
                         expire_seconds: int = 600):
        """Cache scores data (expires in 10 minutes)"""
        key = self._generate_cache_key("scores", sport_key=sport_key, days_from=days_from)
        await self.set(key, data, expire_seconds)
    
    async def get_event_odds(self, sport_key: str, event_id: str, regions: str, 
                             markets: str, odds_format: str, 
                             bookmakers: str = None) -> Optional[Dict[str, Any]]:
        """Get cached event odds data"""
        key = self._generate_cache_key(
            "event_odds",
            sport_key=sport_key,
            event_id=event_id,
            regions=regions,
            markets=markets,
            odds_format=odds_format,
            bookmakers=bookmakers
        )
        return await self.get(key)
    
    async def set_event_odds(self, sport_key: str, event_id: str, regions: str, 
                             markets: str, odds_format: str, data: Dict[str, Any], 
                             bookmakers: str = None, expire_seconds: int = 300):
        """Cache event odds data (expires in 5 minutes)"""
        key = self._generate_cache_key(
            "event_odds",
            sport_key=sport_key,
            event_id=event_id,
            regions=regions,
            markets=markets,
            odds_format=odds_format,
            bookmakers=bookmakers
        )
        await self.set(key, data, expire_seconds)
    
    async def invalidate_sport_caches(self, sport_key: str):
        """Invalidate all caches for a specific sport"""
        patterns = [
            f"odds_api:odds:*sport_key={sport_key}*",
            f"odds_api:scores:*sport_key={sport_key}*",
            f"odds_api:event_odds:*sport_key={sport_key}*"
        ]
        
        for pattern in patterns:
            await self.clear_pattern(pattern)
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        stats = {
            "redis_available": self._redis_available,
            "memory_cache": self._memory_cache.get_stats()
        }
        
        if self._redis_available and await self._test_redis_connection():
            try:
                redis_info = await self._redis_client.info('memory')
                stats["redis"] = {
                    "used_memory": redis_info.get('used_memory_human', 'unknown'),
                    "connected_clients": redis_info.get('connected_clients', 0),
                    "cache_type": "redis"
                }
            except Exception as e:
                stats["redis_error"] = str(e)
        
        return stats

# Global cache instance
cache_service = CacheService()