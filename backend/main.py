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
    ensure_columns,
    ensure_company_rag_default_folders,
    ensure_llm_usage_table,
    ensure_support_tables,
    ensure_pgvector,
    ensure_rls_policies,
    migration_lock,
    migrate_existing_company_memberships,
    migrate_existing_recaps,
    migrate_teams_to_members,
    set_current_company_id,
    set_support_session,
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

# Attach monitoring error capture handler to root logger
from monitoring import error_handler, request_metrics

logging.getLogger().addHandler(error_handler)

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
        errors.append(
            {
                "field": ".".join(str(loc) for loc in err.get("loc", [])),
                "message": err.get("msg", "Validation error"),
                "type": err.get("type", ""),
            }
        )
    logger.warning(
        "Validation error on %s %s: %s",
        request.method,
        request.url.path,
        errors,
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
        exc.status_code,
        request.method,
        request.url.path,
        exc.detail,
    )
    detail_str = str(exc.detail) if exc.detail else "Error"
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "status_code": exc.status_code,
            "message": detail_str,
            "detail": detail_str,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all for unhandled exceptions. Hides details in production."""
    request_id = _request_id.get("-")
    logger.error(
        "Unhandled exception on %s %s [request_id=%s]: %s",
        request.method,
        request.url.path,
        request_id,
        exc,
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
    t0 = time.time()
    response = await call_next(request)
    latency_ms = (time.time() - t0) * 1000
    request_metrics.record(request.method, request.url.path, response.status_code, latency_ms)
    response.headers["X-Request-Id"] = rid
    return response


@app.middleware("http")
async def tenant_isolation_middleware(request: Request, call_next):
    """Extract company_id from JWT and set it in contextvars for RLS."""
    set_current_company_id(None)
    set_support_session(False)
    import jwt as pyjwt

    try:
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
                    if user:
                        effective = user.company_id
                        support_active = False
                        if getattr(user, "is_support", False):
                            # Support account: the active company is the JWT claim
                            # (only honored because is_support is re-checked here).
                            claim = payload.get("active_company_id")
                            if claim is not None:
                                from database import Company

                                exists = db.query(Company.id).filter(Company.id == int(claim)).first()
                                effective = int(claim) if exists else None
                            else:
                                effective = None
                            support_active = effective is not None
                        if effective is not None:
                            set_current_company_id(effective)
                        set_support_session(support_active)
                finally:
                    db.close()
    except pyjwt.PyJWTError:
        # Expected for unauthenticated/invalid tokens — company_id stays None,
        # RLS returns empty result sets (fail-closed).
        pass
    except Exception as exc:
        # Unexpected (e.g. DB error resolving the user). Do not crash the request,
        # but surface it: company_id stays None so RLS still fails closed.
        logger.warning("tenant_isolation_middleware: company_id resolution failed: %s", exc)
    response = await call_next(request)
    return response


@app.middleware("http")
async def support_audit_middleware(request: Request, call_next):
    """Audit every state-changing request made by a support account (self-contained:
    re-derives support state from the token, not contextvars, to avoid middleware
    ordering issues). Best-effort — never breaks the request."""
    response = await call_next(request)
    try:
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.url.path != "/api/support/active-company":
            import jwt as pyjwt

            token = request.cookies.get("token")
            if not token:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    token = auth_header.split(" ")[1]
            if token:
                try:
                    payload = pyjwt.decode(token, os.getenv("JWT_SECRET_KEY", "").strip(), algorithms=["HS256"])
                except Exception:
                    payload = None
                if payload and payload.get("active_company_id") is not None and payload.get("sub"):
                    from database import SupportAuditLog

                    db = SessionLocal()
                    try:
                        u = db.query(User).filter(User.id == int(payload["sub"])).first()
                        if u and getattr(u, "is_support", False):
                            db.add(
                                SupportAuditLog(
                                    support_user_id=int(payload["sub"]),
                                    target_company_id=int(payload["active_company_id"]),
                                    method=request.method,
                                    path=request.url.path[:300],
                                )
                            )
                            db.commit()
                    finally:
                        db.close()
    except Exception as exc:
        logger.warning("support_audit_middleware failed (non-fatal): %s", exc)
    return response


# ---------------------------------------------------------------------------
# CSRF protection middleware (Double Submit Cookie)
# ---------------------------------------------------------------------------
from helpers.csrf import CSRFMiddleware

app.add_middleware(CSRFMiddleware)


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
# Catch-all exception middleware (must sit INSIDE CORSMiddleware so that
# unhandled exceptions still return a proper JSONResponse with CORS headers)
# ---------------------------------------------------------------------------
@app.middleware("http")
async def catch_unhandled_exceptions(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:
        logger.exception("Unhandled exception in %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})


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
    allow_headers=["Content-Type", "Authorization", "Accept", "Origin", "X-Requested-With", "X-CSRF-Token"],
    expose_headers=["Content-Length", "Content-Type", "X-CSRF-Token"],
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
    import time as _time

    t0 = _time.monotonic()

    def _elapsed():
        return f"{_time.monotonic() - t0:.1f}s"

    try:
        logger.info("Initializing database...")
        # WS3: serialize all schema work across concurrent Cloud Run instances.
        with migration_lock():
            # Create tables for brand-new databases (Alembic needs the schema to exist)
            Base.metadata.create_all(bind=engine)
            logger.info("create_all done (%s)", _elapsed())
            # pgvector extension must exist before Alembic migrations touch embedding columns
            ensure_pgvector()
            logger.info("pgvector done (%s)", _elapsed())
            # Add any new columns to existing tables (safe: uses ADD COLUMN IF NOT EXISTS)
            ensure_columns()
            logger.info("ensure_columns done (%s)", _elapsed())
            ensure_company_rag_default_folders()
            logger.info("ensure_company_rag_default_folders done (%s)", _elapsed())
            # Add RLS bypass policies for service operations (email ingestion, etc.)
            ensure_rls_policies()
            logger.info("ensure_rls_policies done (%s)", _elapsed())
            # WS2: LLM usage table + per-company cap column (intentionally NOT in TENANT_TABLES)
            ensure_llm_usage_table()
            logger.info("ensure_llm_usage_table done (%s)", _elapsed())
            # Support account: is_support column + support_audit_logs
            ensure_support_tables()
            logger.info("ensure_support_tables done (%s)", _elapsed())
            # Run Alembic migrations to apply any pending schema changes
            try:
                from alembic.config import Config as AlembicConfig
                from alembic import command as alembic_command

                alembic_cfg = AlembicConfig(os.path.join(os.path.dirname(__file__), "alembic.ini"))
                alembic_cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "alembic"))
                alembic_command.upgrade(alembic_cfg, "head")
                logger.info("Alembic migrations done (%s)", _elapsed())
            except Exception as e:
                # A failed migration blocks every later revision: the schema silently
                # drifts from the models. Log loudly so it never goes unnoticed again.
                logger.error("ALEMBIC MIGRATION FAILED (%s) — schema may be outdated: %s", _elapsed(), e, exc_info=True)
            migrate_existing_company_memberships()
            migrate_existing_recaps()
            migrate_teams_to_members()
            logger.info("Data migrations done (%s)", _elapsed())
        logger.info("Database initialization completed successfully (%s total)", _elapsed())

        # WS4: in production, refuse to start if secrets can't be encrypted.
        if os.getenv("GOOGLE_CLOUD_PROJECT"):
            from encryption import _get_fernet

            _get_fernet()  # raises RuntimeError if ENCRYPTION_KEY is missing
            logger.info("ENCRYPTION_KEY validation passed")

        # Validate GCS bucket is in EU (data sovereignty check)
        try:
            bucket_name = os.getenv("GCS_BUCKET_NAME", "applydi-documents")
            from google.cloud import storage as _gcs_storage

            _gcs_client = _gcs_storage.Client()
            _bucket = _gcs_client.get_bucket(bucket_name)
            _loc = (_bucket.location or "").upper()
            _eu_prefixes = ("EU", "EUROPE")
            if not any(_loc.startswith(p) for p in _eu_prefixes):
                logger.error(
                    f"DATA SOVEREIGNTY VIOLATION: GCS bucket '{bucket_name}' "
                    f"is located in {_loc}, expected EU region. "
                    f"Migrate the bucket to europe-west1."
                )
            else:
                logger.info(f"GCS bucket '{bucket_name}' location: {_loc} (EU compliant)")
        except Exception as e:
            logger.warning(f"Could not verify GCS bucket location: {e}")

        # Start internal recap scheduler
        try:
            from recap_scheduler import start_scheduler

            start_scheduler()
            logger.info("Recap scheduler started")
        except Exception as e:
            logger.warning(f"Recap scheduler failed to start: {e}")

        logger.info("Startup event completed (%s total)", _elapsed())
    except Exception as e:
        logger.error("Database initialization failed (%s): %s", _elapsed(), e)


@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully shut down background services."""
    try:
        from recap_scheduler import shutdown_scheduler

        shutdown_scheduler()
    except Exception as e:
        logger.warning(f"Recap scheduler shutdown error: {e}")


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
from routers.monitoring import router as monitoring_router  # noqa: E402
from routers.support import router as support_router  # noqa: E402
from routers.routines import router as routines_router  # noqa: E402
from routers.graph import router as graph_router  # noqa: E402
from routers.recaps import router as recaps_router  # noqa: E402
from routers.templates import router as templates_router  # noqa: E402
from routers.google_auth import router as google_auth_router  # noqa: E402
from routers.plugins import router as plugins_router  # noqa: E402
from routers.action_executions import router as action_executions_router  # noqa: E402
from routers.automations import router as automations_router  # noqa: E402
from routers.missions import router as missions_router  # noqa: E402
from routers.company_rag import router as company_rag_router  # noqa: E402
from routers.agent_folders import router as agent_folders_router  # noqa: E402

# Discover and register all plugins
from plugins import discover_plugins  # noqa: E402

discover_plugins()

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
app.include_router(monitoring_router)
app.include_router(support_router)
app.include_router(routines_router)
app.include_router(graph_router)
app.include_router(recaps_router)
app.include_router(templates_router)
app.include_router(google_auth_router)
app.include_router(plugins_router)
app.include_router(action_executions_router)
app.include_router(automations_router)
app.include_router(missions_router)
app.include_router(company_rag_router)
app.include_router(agent_folders_router)
