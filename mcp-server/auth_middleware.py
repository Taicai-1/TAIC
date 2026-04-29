"""Bearer token authentication for the MCP server."""

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Validate Authorization: Bearer <token> on every request."""

    async def dispatch(self, request: Request, call_next):
        # Allow health check without auth
        if request.url.path == "/health":
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not _MCP_AUTH_TOKEN:
            # No token configured — reject all requests
            return JSONResponse(
                {"error": "MCP_AUTH_TOKEN not configured"}, status_code=500
            )

        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                {"error": "Missing Authorization header"}, status_code=401
            )

        token = auth_header[len("Bearer ") :]
        if token != _MCP_AUTH_TOKEN:
            return JSONResponse({"error": "Invalid token"}, status_code=403)

        return await call_next(request)
