"""Rate limiting helpers with Redis + in-memory fallback."""

import logging
import time

from redis_client import get_redis

logger = logging.getLogger(__name__)

redis_client = get_redis()

# Fallback in-memory storage (only used if Redis unavailable)
_auth_rate_limit_fallback = {}
_public_chat_rate_fallback = {}
_api_rate_limit_fallback = {}
_org_request_rate_limit_fallback = {}
_2fa_rate_limit_fallback = {}
_password_change_rate_limit_fallback = {}

# Rate limiting configuration
_AUTH_LIMIT = 5  # max failed attempts per window
_AUTH_WINDOW = 3600  # 1 hour in seconds

# Per-user rate limiting for API endpoints (upload, ask, extractText)
_API_UPLOAD_LIMIT = 30  # max uploads per window per user
_API_ASK_LIMIT = 60  # max /ask calls per window per user
_API_EXTRACT_LIMIT = 30  # max extractText calls per window per user
_API_WINDOW = 3600  # 1 hour in seconds

# Rate limiting for org creation request (per IP)
_ORG_REQUEST_LIMIT = 5  # max requests per IP per window
_ORG_REQUEST_WINDOW = 3600  # 1 hour in seconds

# Public chat rate limiting configuration
_PUBLIC_CHAT_LIMIT = 60  # messages per hour per IP
_PUBLIC_CHAT_WINDOW = 3600  # 1 hour in seconds

# 2FA rate limiting configuration
_2FA_LIMIT = 5  # max attempts per window
_2FA_WINDOW = 300  # 5 minutes in seconds

# Password change rate limiting
_PASSWORD_CHANGE_LIMIT = 5
_PASSWORD_CHANGE_WINDOW = 300  # 5 minutes


def _check_api_rate_limit(user_id: str, action: str, limit: int) -> bool:
    """
    Check if user has exceeded rate limit for a specific API action using Redis.
    Returns True if allowed, False if rate limited.
    """
    key = f"rate_limit:{action}:{user_id}"

    if redis_client:
        try:
            current = redis_client.get(key)
            current = int(current) if current else 0
            if current >= limit:
                return False
            pipe = redis_client.pipeline()
            pipe.incr(key)
            pipe.expire(key, _API_WINDOW)
            pipe.execute()
            return True
        except Exception as e:
            logger.error(f"Redis rate limit check failed for {action}: {e}. Using fallback.")

    # Fallback to in-memory
    now = time.time()
    fallback_key = f"{action}:{user_id}"
    attempts = _api_rate_limit_fallback.get(fallback_key, [])
    attempts = [t for t in attempts if now - t < _API_WINDOW]
    if len(attempts) >= limit:
        return False
    attempts.append(now)
    _api_rate_limit_fallback[fallback_key] = attempts
    return True


def _check_org_request_rate_limit(ip: str) -> bool:
    """
    Check if IP has exceeded rate limit for org creation requests.
    Returns True if allowed, False if rate limited.
    Increments counter on every call (unlike _check_auth_rate_limit which
    only counts failures).
    """
    key = f"rate_limit:org_request:{ip}"

    if redis_client:
        try:
            current = redis_client.get(key)
            current = int(current) if current else 0
            if current >= _ORG_REQUEST_LIMIT:
                return False
            pipe = redis_client.pipeline()
            pipe.incr(key)
            pipe.expire(key, _ORG_REQUEST_WINDOW)
            pipe.execute()
            return True
        except Exception as e:
            logger.error(f"Redis org_request rate limit failed: {e}. Using fallback.")

    # Fallback to in-memory
    now = time.time()
    attempts = _org_request_rate_limit_fallback.get(ip, [])
    attempts = [t for t in attempts if now - t < _ORG_REQUEST_WINDOW]
    if len(attempts) >= _ORG_REQUEST_LIMIT:
        return False
    attempts.append(now)
    _org_request_rate_limit_fallback[ip] = attempts
    return True


def _check_auth_rate_limit(ip: str) -> bool:
    """
    Check if IP has exceeded rate limit for auth endpoints.
    Returns True if allowed, False if rate limited.

    Only failed attempts are counted (via _record_auth_failure).
    Max 5 failures per hour per IP.
    """
    key = f"rate_limit:auth:{ip}"

    # Try Redis first
    if redis_client:
        try:
            current = redis_client.get(key)
            current = int(current) if current else 0
            return current < _AUTH_LIMIT
        except Exception as e:
            logger.error(f"Redis rate limit check failed: {e}. Using fallback.")

    # Fallback to in-memory
    now = time.time()
    attempts = _auth_rate_limit_fallback.get(ip, [])
    attempts = [t for t in attempts if now - t < _AUTH_WINDOW]
    _auth_rate_limit_fallback[ip] = attempts
    return len(attempts) < _AUTH_LIMIT


def _record_auth_failure(ip: str):
    """Record a failed auth attempt for rate limiting."""
    key = f"rate_limit:auth:{ip}"

    if redis_client:
        try:
            pipe = redis_client.pipeline()
            pipe.incr(key)
            pipe.expire(key, _AUTH_WINDOW)
            pipe.execute()
            return
        except Exception as e:
            logger.error(f"Redis rate limit record failed: {e}. Using fallback.")

    # Fallback to in-memory
    now = time.time()
    attempts = _auth_rate_limit_fallback.get(ip, [])
    attempts = [t for t in attempts if now - t < _AUTH_WINDOW]
    attempts.append(now)
    _auth_rate_limit_fallback[ip] = attempts


def _check_rate_limit(ip: str):
    """
    Check if IP has exceeded rate limit for public chat using Redis.
    Returns True if allowed, False if rate limited.

    Security: Prevents abuse of public chat endpoints via distributed rate limiting.
    Redis ensures limits work across multiple Cloud Run instances.
    """
    key = f"rate_limit:public_chat:{ip}"

    # Try Redis first
    if redis_client:
        try:
            current = redis_client.get(key)
            current = int(current) if current else 0

            if current >= _PUBLIC_CHAT_LIMIT:
                logger.warning(f"Public chat rate limit exceeded for IP: {ip}")
                return False

            # Increment and set expiration
            pipe = redis_client.pipeline()
            pipe.incr(key)
            pipe.expire(key, _PUBLIC_CHAT_WINDOW)
            pipe.execute()
            return True

        except Exception as e:
            logger.error(f"Redis rate limit check failed: {e}. Using fallback.")

    # Fallback to in-memory (not distributed, but better than nothing)
    now = time.time()
    q = _public_chat_rate_fallback.get(ip, [])
    q = [t for t in q if now - t < _PUBLIC_CHAT_WINDOW]

    if len(q) >= _PUBLIC_CHAT_LIMIT:
        logger.warning(f"Public chat rate limit exceeded for IP (fallback): {ip}")
        return False

    q.append(now)
    _public_chat_rate_fallback[ip] = q
    return True


def _check_2fa_rate_limit(user_id: str) -> bool:
    """Check if user has exceeded 2FA verification rate limit.
    Returns True if allowed, False if rate limited.
    """
    key = f"rate_limit:2fa:{user_id}"

    if redis_client:
        try:
            current = redis_client.get(key)
            current = int(current) if current else 0
            if current >= _2FA_LIMIT:
                return False
            pipe = redis_client.pipeline()
            pipe.incr(key)
            pipe.expire(key, _2FA_WINDOW)
            pipe.execute()
            return True
        except Exception as e:
            logger.error(f"Redis 2FA rate limit check failed: {e}. Using fallback.")

    # Fallback to in-memory
    now = time.time()
    attempts = _2fa_rate_limit_fallback.get(user_id, [])
    attempts = [t for t in attempts if now - t < _2FA_WINDOW]
    if len(attempts) >= _2FA_LIMIT:
        return False
    attempts.append(now)
    _2fa_rate_limit_fallback[user_id] = attempts
    return True


def _check_password_change_rate_limit(user_id: str) -> bool:
    """Check if user has exceeded rate limit for password change. 5 attempts per 5 minutes."""
    key = f"rate_limit:password_change:{user_id}"

    if redis_client:
        try:
            current = redis_client.get(key)
            current = int(current) if current else 0
            if current >= _PASSWORD_CHANGE_LIMIT:
                return False
            pipe = redis_client.pipeline()
            pipe.incr(key)
            pipe.expire(key, _PASSWORD_CHANGE_WINDOW)
            pipe.execute()
            return True
        except Exception as e:
            logger.error(f"Redis rate limit check failed for password change: {e}. Using fallback.")

    now = time.time()
    attempts = _password_change_rate_limit_fallback.get(user_id, [])
    attempts = [t for t in attempts if now - t < _PASSWORD_CHANGE_WINDOW]
    if len(attempts) >= _PASSWORD_CHANGE_LIMIT:
        return False
    attempts.append(now)
    _password_change_rate_limit_fallback[user_id] = attempts
    return True
