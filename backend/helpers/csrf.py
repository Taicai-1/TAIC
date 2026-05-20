"""CSRF Protection Middleware — Response Header Token pattern.

Security: Prevents Cross-Site Request Forgery attacks in a cross-origin SPA setup:

1. The backend generates a random CSRF token per session (stored in a server-side
   cookie for persistence) and sends it in the `X-CSRF-Token` response header.
2. The frontend reads the token from any response header and sends it back
   in the `X-CSRF-Token` request header on state-changing requests.
3. The middleware validates that the request header matches the cookie.

This works cross-origin because:
- The response header is readable by the frontend (via CORS expose_headers).
- An attacker on a different origin cannot read our response headers (Same-Origin Policy).
- Therefore they cannot forge the `X-CSRF-Token` request header.
"""

import hmac
import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Endpoints exempt from CSRF validation (public APIs, webhooks, auth)
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

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"
CSRF_RESPONSE_HEADER = "X-CSRF-Token"


def _is_exempt(path: str) -> bool:
    for exempt in CSRF_EXEMPT_PATHS:
        if path == exempt or path.startswith(exempt):
            return True
    return False


class CSRFMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)

        # Validate CSRF on state-changing requests (only if client has a token)
        if request.method not in SAFE_METHODS and not _is_exempt(request.url.path):
            if csrf_cookie:
                csrf_header = request.headers.get(CSRF_HEADER_NAME)
                if not csrf_header:
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

        # Generate token if client doesn't have one yet
        if not csrf_cookie:
            token = secrets.token_urlsafe(32)
            is_prod = request.url.hostname not in ["localhost", "127.0.0.1"]
            response.set_cookie(
                key=CSRF_COOKIE_NAME,
                value=token,
                httponly=True,  # Not readable by JS — that's fine, we use the header
                secure=is_prod,
                samesite="none" if is_prod else "lax",
                max_age=28800,
                path="/",
            )
            # Send the token in a response header so the frontend can store it
            response.headers[CSRF_RESPONSE_HEADER] = token
        else:
            # Always echo the current token in the response header
            response.headers[CSRF_RESPONSE_HEADER] = csrf_cookie

        return response
