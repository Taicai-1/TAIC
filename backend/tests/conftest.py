import os

# Set required env vars BEFORE any backend imports.
# auth.py calls get_jwt_secret() at import time which reads JWT_SECRET_KEY.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-ci")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
