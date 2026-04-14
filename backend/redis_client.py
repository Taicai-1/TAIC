"""
Shared Redis client singleton for TAIC Companion.

All modules should import get_redis() from here instead of creating
their own connections.  Returns None when Redis is unavailable so
callers can fall back gracefully.
"""

import os
import logging
import redis

logger = logging.getLogger(__name__)

_redis_instance = None
_redis_checked = False


def get_redis():
    """Return a shared Redis client (lazy-init singleton).

    Returns None if the connection cannot be established.
    """
    global _redis_instance, _redis_checked

    if _redis_checked:
        return _redis_instance

    redis_host = os.getenv("REDIS_HOST", "redis")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    redis_password = os.getenv("REDIS_PASSWORD", None)

    try:
        client = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        client.ping()
        _redis_instance = client
        logger.info("Redis client connected successfully.")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}. Features will use fallback mode.")
        _redis_instance = None

    _redis_checked = True
    return _redis_instance


def reset_redis():
    """Force re-check on next get_redis() call (useful for tests)."""
    global _redis_instance, _redis_checked
    _redis_instance = None
    _redis_checked = False


# ---------------------------------------------------------------------------
# User profile cache helpers
# ---------------------------------------------------------------------------
import json

_USER_CACHE_TTL = 600  # 10 minutes
_USER_CACHE_FIELDS = (
    "id",
    "username",
    "email",
    "company_id",
    "email_verified",
    "oauth_provider",
    "totp_enabled",
)


def get_cached_user(user_id, db):
    """Return a User SQLAlchemy object, using Redis cache when possible.

    On cache miss the DB is queried and the result is cached.
    Returns None if the user does not exist.
    """
    from database import User

    uid = int(user_id)
    cache_key = f"user:{uid}"

    # Try Redis first
    r = get_redis()
    if r is not None:
        try:
            cached = r.get(cache_key)
            if cached is not None:
                data = json.loads(cached)
                # We still need the real ORM object for downstream code,
                # but we can merge it from the identity map / session cache
                user = db.query(User).get(uid)
                if user is not None:
                    return user
        except Exception as e:
            logger.debug(f"User cache read failed: {e}")

    # DB query (cache miss or Redis unavailable)
    user = db.query(User).filter(User.id == uid).first()

    if user is not None and r is not None:
        try:
            data = {f: getattr(user, f, None) for f in _USER_CACHE_FIELDS}
            r.setex(cache_key, _USER_CACHE_TTL, json.dumps(data, default=str))
        except Exception as e:
            logger.debug(f"User cache write failed: {e}")

    return user


def invalidate_user_cache(user_id):
    """Delete cached user profile so the next read fetches fresh data."""
    r = get_redis()
    if r is None:
        return
    try:
        r.delete(f"user:{int(user_id)}")
    except Exception as e:
        logger.debug(f"User cache invalidate failed: {e}")
