"""TAIC Companion API – FastAPI application entry point.

Responsibilities kept here:
  - App creation, CORS, security headers, tenant-isolation middleware
  - Static file mounts
  - Startup event (DB init)
  - Health-check endpoints (/, /health)
  - Router registration (all business logic lives in routers/)
"""

import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from database import (
    Base,
    SessionLocal,
    User,
    engine,
    ensure_columns,
    ensure_pgvector,
    init_db,
    migrate_existing_company_memberships,
    set_current_company_id,
)
from utils import logger  # noqa: F811 – overridden below in prod

# ---------------------------------------------------------------------------
# Logging (Google Cloud Logging in production, basic otherwise)
# ---------------------------------------------------------------------------
if os.getenv("GOOGLE_CLOUD_PROJECT"):
    try:
        from google.cloud import logging as cloud_logging

        client = cloud_logging.Client()
        client.setup_logging()
        logger = logging.getLogger("app")
    except ImportError:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
        logger = logging.getLogger("app")
else:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger("app")

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(title="TAIC Companion API", version="1.0.0")


# ---------------------------------------------------------------------------
# Tenant isolation middleware (sets company_id for RLS via contextvars)
# ---------------------------------------------------------------------------
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
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

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
    """Initialize database and create tables on startup."""
    try:
        logger.info("Initializing database...")
        init_db()
        logger.info("Creating database tables...")
        Base.metadata.create_all(bind=engine)
        ensure_columns()
        ensure_pgvector()
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
    """Health check endpoint"""
    return {"status": "healthy", "service": "TAIC Companion API"}


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
