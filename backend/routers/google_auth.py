"""Google OAuth2 endpoints for connecting user Google accounts."""

import json
import logging
import os
from datetime import datetime, timedelta

os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from auth import verify_token
from database import get_db, UserGoogleToken
from google_credentials import check_scopes_covered

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/google", tags=["google-auth"])

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8080/auth/google/callback")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


def _build_client_config():
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI],
        }
    }


@router.get("/authorize")
async def google_authorize(
    scopes: str = Query(..., description="Comma-separated Google API scopes"),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Generate a Google OAuth2 authorization URL."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")

    scope_list = [s.strip() for s in scopes.split(",") if s.strip()]
    if not scope_list:
        raise HTTPException(status_code=400, detail="At least one scope is required")

    flow = Flow.from_client_config(
        _build_client_config(),
        scopes=scope_list,
        redirect_uri=GOOGLE_REDIRECT_URI,
    )
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=user_id,
    )
    return {"authorization_url": authorization_url}


@router.get("/callback")
async def google_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    """Handle OAuth2 callback from Google. Exchange code for tokens and store."""
    try:
        user_id = int(state)

        flow = Flow.from_client_config(
            _build_client_config(),
            scopes=[],
            redirect_uri=GOOGLE_REDIRECT_URI,
        )
        flow.fetch_token(code=code)
        credentials = flow.credentials

        granted_scopes = list(credentials.scopes) if credentials.scopes else []

        existing = db.query(UserGoogleToken).filter(UserGoogleToken.user_id == user_id).first()
        if existing:
            existing.access_token = credentials.token
            existing.refresh_token = credentials.refresh_token or existing.refresh_token
            existing.token_expiry = credentials.expiry or (datetime.utcnow() + timedelta(hours=1))
            old_scopes = json.loads(existing.granted_scopes) if existing.granted_scopes else []
            merged = list(set(old_scopes + granted_scopes))
            existing.granted_scopes = json.dumps(merged)
            existing.updated_at = datetime.utcnow()
        else:
            token_row = UserGoogleToken(
                user_id=user_id,
                token_expiry=credentials.expiry or (datetime.utcnow() + timedelta(hours=1)),
                granted_scopes=json.dumps(granted_scopes),
            )
            token_row.access_token = credentials.token
            token_row.refresh_token = credentials.refresh_token or ""
            db.add(token_row)

        db.commit()
        logger.info(f"Stored Google OAuth token for user {user_id}, scopes={granted_scopes}")

        return RedirectResponse(url=f"{FRONTEND_URL}/agents?google_connected=true")
    except Exception as e:
        logger.error(f"Google OAuth callback failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"OAuth callback error: {e}")


@router.get("/status")
async def google_status(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Check if the user has a connected Google account and which scopes are granted."""
    token = db.query(UserGoogleToken).filter(UserGoogleToken.user_id == int(user_id)).first()
    if not token:
        return {"connected": False, "granted_scopes": []}

    granted = json.loads(token.granted_scopes) if token.granted_scopes else []
    expired = token.token_expiry < datetime.utcnow()
    return {"connected": True, "granted_scopes": granted, "token_expired": expired}


@router.delete("/revoke")
async def google_revoke(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Revoke Google tokens and delete from database."""
    token = db.query(UserGoogleToken).filter(UserGoogleToken.user_id == int(user_id)).first()
    if not token:
        raise HTTPException(status_code=404, detail="No Google account connected")

    try:
        import requests

        requests.post(
            "https://oauth2.googleapis.com/revoke",
            params={"token": token.access_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
    except Exception:
        logger.warning(f"Failed to revoke token at Google for user {user_id}")

    db.delete(token)
    db.commit()
    return {"status": "revoked"}
