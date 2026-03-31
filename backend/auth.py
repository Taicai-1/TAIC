import jwt
import bcrypt
from datetime import datetime, timedelta
from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import os
import logging

logger = logging.getLogger(__name__)

def get_jwt_secret():
    """Get JWT secret from environment (injected by GCP Secret Manager)"""
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        logger.error("JWT secret not found! Set JWT_SECRET_KEY via Secret Manager for production.")
        raise RuntimeError("JWT secret missing. Set JWT_SECRET_KEY in environment for production.")
    logger.info("JWT secret loaded from environment")
    return secret.strip()

SECRET_KEY = get_jwt_secret()
ALGORITHM = "HS256"

# Restricted token types that must NOT access application endpoints
RESTRICTED_TOKEN_TYPES = {"pre_2fa", "needs_2fa_setup"}

security = HTTPBearer()

def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    """Verify password against hash"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def create_access_token(data: dict, expires_delta: timedelta = None):
    """Create JWT token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=8)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def _extract_token(request: Request) -> str:
    """Extract token from cookie or Authorization header."""
    token = request.cookies.get("token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return token

def _decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Returns the payload."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("sub") is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return payload
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify JWT token from Authorization header and extract user info.
    Rejects restricted 2FA tokens.
    """
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        # Reject restricted tokens
        token_type = payload.get("type")
        if token_type in RESTRICTED_TOKEN_TYPES:
            raise HTTPException(status_code=403, detail="2FA verification required")
        return user_id
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def verify_token_from_cookie(request: Request):
    """Verify JWT token from HttpOnly cookie or Authorization header.
    Rejects restricted 2FA tokens.
    """
    token = _extract_token(request)
    payload = _decode_token(token)
    # Reject restricted tokens
    token_type = payload.get("type")
    if token_type in RESTRICTED_TOKEN_TYPES:
        raise HTTPException(status_code=403, detail="2FA verification required")
    return payload.get("sub")

def _extract_token_from_header(request: Request) -> str:
    """Extract token from Authorization header ONLY (not cookies).
    Used for restricted tokens (pre_2fa, setup) that are never stored in cookies.
    """
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ")[1]
    raise HTTPException(status_code=401, detail="Not authenticated")

def verify_pre_2fa_token(request: Request) -> str:
    """Verify a pre-2FA token (issued after password check, before TOTP verification).
    Only accepts tokens with type='pre_2fa'. Reads from Authorization header only.
    """
    token = _extract_token_from_header(request)
    payload = _decode_token(token)
    if payload.get("type") != "pre_2fa":
        raise HTTPException(status_code=401, detail="Invalid pre-2FA token")
    return payload.get("sub")

def verify_setup_token(request: Request) -> str:
    """Verify a 2FA setup token (issued for users who need to configure 2FA).
    Only accepts tokens with type='needs_2fa_setup'. Reads from Authorization header only.
    """
    token = _extract_token_from_header(request)
    payload = _decode_token(token)
    if payload.get("type") != "needs_2fa_setup":
        raise HTTPException(status_code=401, detail="Invalid setup token")
    return payload.get("sub")

def hash_reset_token(token: str) -> str:
    """Hash a password reset token using SHA-256.
    Uses deterministic hashing to allow database lookups.

    Security: Reset tokens are hashed before storage to prevent theft
    if the database is compromised. Uses SHA-256 (not bcrypt) because
    we need to look up tokens in the database by hash.
    """
    import hashlib
    return hashlib.sha256(token.encode('utf-8')).hexdigest()
