"""OAuth 2.1 authorization proxy for the MCP server.

Acts as its own OAuth authorization server (RFC 8414) and delegates
identity verification to Google OAuth. Implements PKCE (S256) and
issues JWT access tokens for MCP clients like Claude Code.

Discovery chain (from Claude Code's perspective):
  1. POST /mcp -> 401
  2. GET /.well-known/oauth-protected-resource -> points to self as AS
  3. GET /.well-known/oauth-authorization-server -> authorize/token endpoints
  4. GET /authorize -> redirects browser to Google
  5. Google callback -> /oauth/callback -> redirects to Claude Code with MCP code
  6. POST /token -> exchanges MCP code + PKCE for JWT
"""

import base64
import hashlib
import logging
import os
import secrets
import time
from urllib.parse import urlencode

import httpx
import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
ALLOWED_DOMAIN = "taic.co"

PENDING_AUTH_TTL = 300  # 5 min
AUTH_CODE_TTL = 300  # 5 min
ACCESS_TOKEN_TTL = 86400  # 24 h


class _Store:
    """In-memory key-value store with TTL expiry."""

    def __init__(self):
        self._data: dict[str, dict] = {}

    def set(self, key: str, value: dict, ttl: int):
        value["_exp"] = time.time() + ttl
        self._data[key] = value

    def get(self, key: str) -> dict | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        if time.time() > entry["_exp"]:
            del self._data[key]
            return None
        return entry

    def pop(self, key: str) -> dict | None:
        entry = self.get(key)
        if entry is not None:
            del self._data[key]
        return entry


class MCPAuthMiddleware(BaseHTTPMiddleware):
    """OAuth 2.1 proxy middleware — delegates identity to Google."""

    def __init__(
        self,
        app,
        *,
        server_url: str,
        google_client_id: str,
        google_client_secret: str,
        jwt_secret: str,
    ):
        super().__init__(app)
        self.server_url = server_url.rstrip("/")
        self.google_client_id = google_client_id
        self.google_client_secret = google_client_secret
        self.jwt_secret = jwt_secret
        self._pending = _Store()
        self._codes = _Store()

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path == "/health":
            return await call_next(request)
        if path == "/.well-known/oauth-protected-resource":
            return self._resource_metadata()
        if path == "/.well-known/oauth-authorization-server":
            return self._as_metadata()
        if path == "/authorize":
            return self._handle_authorize(request)
        if path == "/oauth/callback":
            return await self._handle_callback(request)
        if path == "/token":
            return await self._handle_token(request)
        if path == "/register":
            return await self._handle_register(request)

        # ── Protected paths — require JWT ─────────────────────────────
        email = self._validate_jwt(request)
        if email is None:
            return JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="taic-mcp"'},
            )
        request.state.user_email = email
        return await call_next(request)

    # ── Discovery ─────────────────────────────────────────────────────

    def _resource_metadata(self) -> JSONResponse:
        """RFC 9728 Protected Resource Metadata."""
        return JSONResponse(
            {
                "resource": self.server_url,
                "authorization_servers": [self.server_url],
                "scopes_supported": ["openid", "email"],
                "bearer_methods_supported": ["header"],
            },
            headers={"Access-Control-Allow-Origin": "*"},
        )

    def _as_metadata(self) -> JSONResponse:
        """RFC 8414 Authorization Server Metadata."""
        return JSONResponse(
            {
                "issuer": self.server_url,
                "authorization_endpoint": f"{self.server_url}/authorize",
                "token_endpoint": f"{self.server_url}/token",
                "registration_endpoint": f"{self.server_url}/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
                "scopes_supported": ["openid", "email"],
            },
            headers={"Access-Control-Allow-Origin": "*"},
        )

    # ── OAuth flow ────────────────────────────────────────────────────

    def _handle_authorize(self, request: Request) -> RedirectResponse | JSONResponse:
        """Start OAuth — store PKCE params, redirect to Google."""
        p = request.query_params
        if p.get("code_challenge_method") != "S256":
            return JSONResponse(
                {"error": "invalid_request", "error_description": "S256 required"},
                status_code=400,
            )

        google_state = secrets.token_urlsafe(32)
        self._pending.set(
            google_state,
            {
                "code_challenge": p.get("code_challenge", ""),
                "redirect_uri": p.get("redirect_uri", ""),
                "client_state": p.get("state", ""),
                "client_id": p.get("client_id", ""),
            },
            PENDING_AUTH_TTL,
        )

        google_params = urlencode(
            {
                "client_id": self.google_client_id,
                "redirect_uri": f"{self.server_url}/oauth/callback",
                "response_type": "code",
                "scope": "openid email",
                "state": google_state,
                "access_type": "online",
                "prompt": "select_account",
            }
        )
        return RedirectResponse(f"{GOOGLE_AUTH_URL}?{google_params}")

    async def _handle_callback(self, request: Request):
        """Google redirects here — validate email, redirect to client."""
        p = request.query_params
        google_state = p.get("state", "")
        pending = self._pending.pop(google_state)
        if pending is None:
            return JSONResponse({"error": "invalid_state"}, status_code=400)

        if p.get("error"):
            return self._error_redirect(
                pending["redirect_uri"],
                pending["client_state"],
                "access_denied",
                f"Google error: {p.get('error')}",
            )

        email = await self._exchange_google_code(p.get("code", ""))
        if email is None:
            return self._error_redirect(
                pending["redirect_uri"],
                pending["client_state"],
                "access_denied",
                "Google identity verification failed",
            )

        if not email.endswith(f"@{ALLOWED_DOMAIN}"):
            logger.warning("Rejected email: %s", email)
            return self._error_redirect(
                pending["redirect_uri"],
                pending["client_state"],
                "access_denied",
                f"Only @{ALLOWED_DOMAIN} accounts allowed",
            )

        mcp_code = secrets.token_urlsafe(32)
        self._codes.set(
            mcp_code,
            {
                "email": email,
                "code_challenge": pending["code_challenge"],
                "redirect_uri": pending["redirect_uri"],
                "client_id": pending["client_id"],
            },
            AUTH_CODE_TTL,
        )

        qs = urlencode({"code": mcp_code, "state": pending["client_state"]})
        return RedirectResponse(f"{pending['redirect_uri']}?{qs}")

    async def _handle_token(self, request: Request) -> JSONResponse:
        """Exchange MCP auth code + PKCE verifier for JWT."""
        ct = request.headers.get("content-type", "")
        if "application/x-www-form-urlencoded" in ct:
            raw = await request.form()
            data = dict(raw)
        else:
            data = await request.json()

        if data.get("grant_type") != "authorization_code":
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

        auth = self._codes.pop(data.get("code", ""))
        if auth is None:
            return JSONResponse(
                {"error": "invalid_grant", "error_description": "Invalid or expired code"},
                status_code=400,
            )

        if not self._verify_pkce(data.get("code_verifier", ""), auth["code_challenge"]):
            return JSONResponse(
                {"error": "invalid_grant", "error_description": "PKCE verification failed"},
                status_code=400,
            )

        now = int(time.time())
        token = jwt.encode(
            {
                "sub": auth["email"],
                "iss": self.server_url,
                "aud": "taic-mcp",
                "iat": now,
                "exp": now + ACCESS_TOKEN_TTL,
            },
            self.jwt_secret,
            algorithm="HS256",
        )

        logger.info("Issued MCP token for %s", auth["email"])
        return JSONResponse({
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_TTL,
        })

    async def _handle_register(self, request: Request) -> JSONResponse:
        """RFC 7591 Dynamic Client Registration (simplified)."""
        body = await request.json()
        return JSONResponse(
            {
                "client_id": secrets.token_urlsafe(16),
                "client_name": body.get("client_name", "MCP Client"),
                "redirect_uris": body.get("redirect_uris", []),
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
            status_code=201,
        )

    # ── Helpers ───────────────────────────────────────────────────────

    def _validate_jwt(self, request: Request) -> str | None:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return None
        try:
            payload = jwt.decode(
                auth.removeprefix("Bearer "),
                self.jwt_secret,
                algorithms=["HS256"],
                audience="taic-mcp",
            )
            return payload.get("sub")
        except jwt.InvalidTokenError as exc:
            logger.debug("JWT invalid: %s", exc)
            return None

    async def _exchange_google_code(self, code: str) -> str | None:
        """Exchange Google auth code for user email."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "code": code,
                        "client_id": self.google_client_id,
                        "client_secret": self.google_client_secret,
                        "redirect_uri": f"{self.server_url}/oauth/callback",
                        "grant_type": "authorization_code",
                    },
                )
            if resp.status_code != 200:
                logger.warning("Google token exchange failed: %s", resp.text)
                return None

            access_token = resp.json().get("access_token")
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if resp.status_code != 200:
                return None

            info = resp.json()
            if not info.get("email_verified"):
                return None
            return info.get("email")

        except httpx.HTTPError as exc:
            logger.error("Google exchange error: %s", exc)
            return None

    @staticmethod
    def _verify_pkce(code_verifier: str, code_challenge: str) -> bool:
        if not code_verifier or not code_challenge:
            return False
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return computed == code_challenge

    @staticmethod
    def _error_redirect(redirect_uri, state, error, description):
        qs = urlencode({"error": error, "error_description": description, "state": state})
        return RedirectResponse(f"{redirect_uri}?{qs}")
