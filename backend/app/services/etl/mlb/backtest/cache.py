"""SQLite API Response Cache for Backtesting.

Caches all MLB-StatsAPI and Odds API responses to avoid redundant calls
and burning API quota. Keyed by (endpoint, params_hash).

REQ-BT-063: Cache all API responses to local SQLite database.
REQ-BT-064: Support --clear-cache and --cache-only modes.
"""
import hashlib
import json
import logging
import os
import sqlite3
import time

logger = logging.getLogger(__name__)

def _backend_scripts_dir() -> str:
    # .../backend/app/services/etl/mlb/backtest/cache.py -> backend/scripts
    return os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "scripts")


CACHE_DB_PATH = os.path.join(_backend_scripts_dir(), "mlb_backtest_cache.db")

# Rate limiting: max 10 requests/second for MLB-StatsAPI (REQ-BT-062)
_last_request_time = 0.0
REQUEST_INTERVAL = 0.1  # 100ms between requests


def _get_connection():
    """Get SQLite connection, creating the database and table if needed."""
    db_path = os.path.abspath(CACHE_DB_PATH)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_cache (
            cache_key TEXT PRIMARY KEY,
            endpoint TEXT NOT NULL,
            params_json TEXT,
            response_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    conn.commit()
    return conn


def _make_cache_key(endpoint, params):
    """Create a deterministic cache key from endpoint and parameters."""
    params_str = json.dumps(params, sort_keys=True, default=str)
    raw = f"{endpoint}|{params_str}"
    return hashlib.sha256(raw.encode()).hexdigest()


def get_cached(endpoint, params):
    """Retrieve a cached API response.

    Returns:
        dict/list or None if not cached.
    """
    key = _make_cache_key(endpoint, params)
    try:
        conn = _get_connection()
        cur = conn.execute(
            "SELECT response_json FROM api_cache WHERE cache_key = ?", (key,)
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
    except Exception as e:
        logger.debug(f"Cache read error: {e}")
    return None


def set_cached(endpoint, params, response):
    """Store an API response in the cache."""
    key = _make_cache_key(endpoint, params)
    try:
        conn = _get_connection()
        conn.execute(
            """INSERT OR REPLACE INTO api_cache
               (cache_key, endpoint, params_json, response_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (key, endpoint, json.dumps(params, sort_keys=True, default=str),
             json.dumps(response, default=str), time.time())
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"Cache write error: {e}")


def clear_cache():
    """Delete all cached entries (REQ-BT-064)."""
    db_path = os.path.abspath(CACHE_DB_PATH)
    if os.path.exists(db_path):
        os.remove(db_path)
        logger.info("Cache cleared")
    else:
        logger.info("No cache to clear")


def get_cache_stats():
    """Return cache statistics."""
    try:
        conn = _get_connection()
        cur = conn.execute("SELECT COUNT(*), COUNT(DISTINCT endpoint) FROM api_cache")
        row = cur.fetchone()
        conn.close()
        return {'total_entries': row[0], 'unique_endpoints': row[1]}
    except Exception:
        return {'total_entries': 0, 'unique_endpoints': 0}


def rate_limit():
    """Enforce rate limiting between API requests (REQ-BT-062)."""
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < REQUEST_INTERVAL:
        time.sleep(REQUEST_INTERVAL - elapsed)
    _last_request_time = time.time()


def cached_api_call(endpoint, params, fetch_fn, cache_only=False):
    """Wrapper that checks cache before making an API call.

    Args:
        endpoint: API endpoint identifier string
        params: dict of parameters
        fetch_fn: callable that returns the API response
        cache_only: if True, never make API calls

    Returns:
        API response (dict/list) or None if cache_only and not cached
    """
    cached = get_cached(endpoint, params)
    if cached is not None:
        return cached

    if cache_only:
        return None

    rate_limit()
    try:
        response = fetch_fn()
        if response is not None:
            set_cached(endpoint, params, response)
        return response
    except Exception as e:
        logger.warning(f"API call failed for {endpoint}: {e}")
        return None
