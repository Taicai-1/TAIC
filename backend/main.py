"""TAIC Companion API – FastAPI application entry point.

Responsibilities kept here:
  - App creation, CORS, security headers, tenant-isolation middleware
  - Centralized error handling (exception handlers)
  - Structured JSON logging with request_id tracing
  - Static file mounts
  - Startup event (DB init)
  - Health-check endpoints (/, /health)
  - Router registration (all business logic lives in routers/)
"""

import logging
import os
import time
import traceback
import uuid

from contextvars import ContextVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pythonjsonlogger import json as jsonlogger

from database import (
    Base,
    SessionLocal,
    User,
    engine,
    ensure_pgvector,
    migrate_existing_company_memberships,
    set_current_company_id,
)

# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Context variable for per-request tracing
_request_id: ContextVar[str] = ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    """Inject current request_id into every log record."""

    def filter(self, record):
        record.request_id = _request_id.get("-")
        return True


def _setup_logging():
    """Configure structured JSON logging for all environments."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Remove any existing handlers to avoid duplicates on reload
    root.handlers.clear()

    if os.getenv("GOOGLE_CLOUD_PROJECT"):
        # Production on GCP: google-cloud-logging already emits JSON
        try:
            from google.cloud import logging as cloud_logging

            client = cloud_logging.Client()
            client.setup_logging()
            # Add request_id filter to all handlers set up by GCP
            rid_filter = _RequestIdFilter()
            for h in root.handlers:
                h.addFilter(rid_filter)
            return
        except ImportError:
            pass  # Fall through to manual JSON setup

    # All other environments: JSON via python-json-logger
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
        rename_fields={"asctime": "timestamp", "levelname": "severity"},
    )
    if ENVIRONMENT == "development":
        # Pretty-print JSON in dev for readability
        formatter.json_indent = 2
    handler.setFormatter(formatter)
    handler.addFilter(_RequestIdFilter())
    root.addHandler(handler)


_setup_logging()
logger = logging.getLogger("app")

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(title="TAIC Companion API", version="1.0.0")


# ---------------------------------------------------------------------------
# Centralized exception handlers
# ---------------------------------------------------------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return structured 422 for validation errors."""
    errors = []
    for err in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in err.get("loc", [])),
            "message": err.get("msg", "Validation error"),
            "type": err.get("type", ""),
        })
    logger.warning(
        "Validation error on %s %s: %s",
        request.method, request.url.path, errors,
    )
    return JSONResponse(
        status_code=422,
        content={
            "error": True,
            "status_code": 422,
            "message": "Validation error",
            "detail": errors,
        },
    )


from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Return structured JSON for all HTTP errors."""
    logger.warning(
        "HTTP %d on %s %s: %s",
        exc.status_code, request.method, request.url.path, exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "status_code": exc.status_code,
            "message": str(exc.detail) if exc.detail else "Error",
            "detail": None,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all for unhandled exceptions. Hides details in production."""
    request_id = _request_id.get("-")
    logger.error(
        "Unhandled exception on %s %s [request_id=%s]: %s",
        request.method, request.url.path, request_id, exc,
        exc_info=True,
    )
    detail = None
    if ENVIRONMENT == "development":
        detail = {
            "exception": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exception(type(exc), exc, exc.__traceback__),
        }
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "status_code": 500,
            "message": "Internal Server Error" if ENVIRONMENT != "development" else str(exc),
            "detail": detail,
            "request_id": request_id,
        },
    )


# ---------------------------------------------------------------------------
# Request ID + tenant isolation middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Assign a unique request_id to every request for log tracing."""
    rid = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    _request_id.set(rid)
    response = await call_next(request)
    response.headers["X-Request-Id"] = rid
    return response


@app.middleware("http")
async def tenant_isolation_middleware(request: Request, call_next):
    """Extract company_id from JWT and set it in contextvars for RLS."""
    set_current_company_id(None)
    try:
        import jwt as pyjwt

        token = request.cookies.get("token")
        if not token:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]
        if token:
            secret = os.getenv("JWT_SECRET_KEY", "").strip()
            payload = pyjwt.decode(token, secret, algorithms=["HS256"])
            user_id = payload.get("sub")
            token_type = payload.get("type")
            # Skip restricted tokens (pre-2FA)
            if user_id and token_type not in ("pre_2fa", "needs_2fa_setup"):
                db = SessionLocal()
                try:
                    user = db.query(User).filter(User.id == int(user_id)).first()
                    if user and user.company_id:
                        set_current_company_id(user.company_id)
                finally:
                    db.close()
    except Exception:
        pass  # Unauthenticated requests — company_id stays None, RLS returns empty
    response = await call_next(request)
    return response


# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)

    # HSTS: Force HTTPS for 1 year (only in production)
    if request.url.hostname not in ["localhost", "127.0.0.1"]:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # CSP: Prevent XSS attacks
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https://api.openai.com https://api.mistral.ai https://generativelanguage.googleapis.com; "
        "frame-ancestors 'none';"
    )

    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

    return response


# ---------------------------------------------------------------------------
# CORS configuration
# ---------------------------------------------------------------------------
allowed_origins = [
    "https://taic.ai",
    "https://www.taic.ai",
    "https://dev-taic-frontend-817946451913.europe-west1.run.app",
    "https://applydi-frontend-817946451913.europe-west1.run.app",
]

if ENVIRONMENT == "development":
    allowed_origins.extend(["http://localhost:3000", "http://localhost:8080"])
    logger.info("CORS: Development mode - localhost origins enabled")
else:
    logger.info("CORS: Production mode - localhost origins disabled")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"^https://([\w-]+\.taic\.ai|[\w-]+-817946451913\.europe-west1\.run\.app)$"
    if ENVIRONMENT == "production"
    else None,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Content-Type", "Authorization", "Accept", "Origin", "X-Requested-With"],
    expose_headers=["Content-Length", "Content-Type"],
    max_age=600,
)


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
if not os.path.exists("profile_photos"):
    os.makedirs("profile_photos")
app.mount("/profile_photos", StaticFiles(directory="profile_photos"), name="profile_photos")


# ---------------------------------------------------------------------------
# Startup event
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    """Initialize database and run Alembic migrations on startup."""
    try:
        logger.info("Initializing database...")
        # Create tables for brand-new databases (Alembic needs the schema to exist)
        Base.metadata.create_all(bind=engine)
        # pgvector extension must exist before Alembic migrations touch embedding columns
        ensure_pgvector()
        # Run Alembic migrations to apply any pending schema changes
        from alembic.config import Config as AlembicConfig
        from alembic import command as alembic_command

        alembic_cfg = AlembicConfig(os.path.join(os.path.dirname(__file__), "alembic.ini"))
        alembic_cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "alembic"))
        alembic_command.upgrade(alembic_cfg, "head")
        logger.info("Alembic migrations applied successfully")
        migrate_existing_company_memberships()
        logger.info("Database initialization completed successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")


# ---------------------------------------------------------------------------
# Health-check endpoints
# ---------------------------------------------------------------------------
@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "TAIC Companion API is running", "status": "ok"}


@app.get("/health")
async def health_check():
    """Health check with actual PostgreSQL and Redis connectivity tests."""
    from redis_client import get_redis
    from sqlalchemy import text

    checks = {}

    # -- PostgreSQL --
    t0 = time.time()
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            latency = round((time.time() - t0) * 1000, 1)
            pool = engine.pool
            checks["database"] = {
                "status": "up",
                "latency_ms": latency,
                "pool": {
                    "size": pool.size(),
                    "checked_in": pool.checkedin(),
                    "checked_out": pool.checkedout(),
                    "overflow": pool.overflow(),
                },
            }
        finally:
            db.close()
    except Exception as e:
        latency = round((time.time() - t0) * 1000, 1)
        checks["database"] = {"status": "down", "latency_ms": latency, "error": str(e)}

    # -- Redis --
    t0 = time.time()
    try:
        r = get_redis()
        if r is not None:
            r.ping()
            latency = round((time.time() - t0) * 1000, 1)
            checks["redis"] = {"status": "up", "latency_ms": latency}
        else:
            checks["redis"] = {"status": "unavailable", "latency_ms": 0}
    except Exception as e:
        latency = round((time.time() - t0) * 1000, 1)
        checks["redis"] = {"status": "down", "latency_ms": latency, "error": str(e)}

    # -- Overall status --
    db_up = checks["database"]["status"] == "up"
    redis_up = checks["redis"]["status"] == "up"

    if db_up and redis_up:
        overall = "healthy"
    elif db_up:
        overall = "degraded"
    else:
        overall = "unhealthy"

    status_code = 200 if db_up else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": overall, "service": "TAIC Companion API", "checks": checks},
    )


# ---------------------------------------------------------------------------
# Router registration
# ---------------------------------------------------------------------------
from routers.auth import router as auth_router  # noqa: E402
from routers.ask import router as ask_router  # noqa: E402
from routers.documents import router as documents_router  # noqa: E402
from routers.agents import router as agents_router  # noqa: E402
from routers.sources import router as sources_router  # noqa: E402
from routers.conversations import router as conversations_router  # noqa: E402
from routers.slack import router as slack_router  # noqa: E402
from routers.public import router as public_router  # noqa: E402
from routers.email_ingest import router as email_ingest_router  # noqa: E402
from routers.organization import router as organization_router  # noqa: E402
from routers.user import router as user_router  # noqa: E402

app.include_router(auth_router)
app.include_router(ask_router)
app.include_router(documents_router)
app.include_router(agents_router)
app.include_router(sources_router)
app.include_router(conversations_router)
app.include_router(slack_router)
app.include_router(public_router)
app.include_router(email_ingest_router)
app.include_router(organization_router)
app.include_router(user_router)
