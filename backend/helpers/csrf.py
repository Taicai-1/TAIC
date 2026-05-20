"""CSRF Protection Middleware — Double Submit Cookie pattern.

Security: Prevents Cross-Site Request Forgery attacks by:
1. Setting a random CSRF token as a non-HttpOnly cookie (readable by JS)
2. Requiring state-changing requests (POST, PUT, DELETE, PATCH) to include
   the same token in the X-CSRF-Token header
3. Validating that both values match using constant-time comparison

The cookie is non-HttpOnly so the frontend can read and send it as a header.
The attacker cannot read the cookie from a different origin (Same-Origin Policy),
so they cannot forge the header value.
"""

import hmac
import logging
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Endpoints exempt from CSRF validation (public APIs, webhooks, login/register)
CSRF_EXEMPT_PATHS = {
    "/login",
    "/register",
    "/auth/",
    "/health",
    "/docs",
    "/openapi.json",
    "/public/",
    "/slack/events",
    "/email-ingest",
    "/api/routines/",
    "/forgot-password",
    "/reset-password",
}

# Methods that don't change state — no CSRF check needed
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"


def _is_exempt(path: str) -> bool:
    """Check if the request path is exempt from CSRF validation."""
    for exempt in CSRF_EXEMPT_PATHS:
        if path == exempt or path.startswith(exempt):
            return True
    return False


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double Submit Cookie CSRF protection middleware."""

    async def dispatch(self, request: Request, call_next):
        # Always set CSRF cookie if not present (for any request)
        response = None
        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)

        if request.method not in SAFE_METHODS and not _is_exempt(request.url.path):
            # Validate CSRF token for state-changing requests
            csrf_header = request.headers.get(CSRF_HEADER_NAME)

            if not csrf_cookie or not csrf_header:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token missing"},
                )

            if not hmac.compare_digest(csrf_cookie, csrf_header):
                logger.warning(f"CSRF token mismatch for {request.method} {request.url.path}")
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token mismatch"},
                )

        response = await call_next(request)

        # Set CSRF cookie if not already present
        if not csrf_cookie:
            token = secrets.token_urlsafe(32)
            is_prod = request.url.hostname not in ["localhost", "127.0.0.1"]
            response.set_cookie(
                key=CSRF_COOKIE_NAME,
                value=token,
                httponly=False,  # Must be readable by JavaScript
                secure=is_prod,
                samesite="none" if is_prod else "lax",
                max_age=28800,
                path="/",
            )

        return response
