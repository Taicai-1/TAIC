"""Google OAuth2 credential management: load, refresh, and scope checking."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from google.auth.transport import requests as google_requests
from sqlalchemy.orm import Session

from database import UserGoogleToken

logger = logging.getLogger(__name__)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
TOKEN_URI = "https://oauth2.googleapis.com/token"


def get_google_credentials(user_id: int, db: Session) -> Credentials | None:
    """Load Google OAuth2 credentials for a user. Refreshes if expired.

    Returns None if the user has no stored token.
    """
    token_row = db.query(UserGoogleToken).filter(UserGoogleToken.user_id == user_id).first()
    if token_row is None:
        return None

    granted = json.loads(token_row.granted_scopes) if token_row.granted_scopes else []

    creds = Credentials(
        token=token_row.access_token,
        refresh_token=token_row.refresh_token,
        token_uri=TOKEN_URI,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=granted,
    )

    # Check if token is expired and refresh
    if token_row.token_expiry < datetime.utcnow():
        try:
            creds.refresh(google_requests.Request())
            # Update stored token
            token_row.access_token = creds.token
            token_row.token_expiry = creds.expiry or (datetime.utcnow() + timedelta(hours=1))
            token_row.updated_at = datetime.utcnow()
            db.commit()
            logger.info(f"Refreshed Google token for user {user_id}")
        except Exception:
            logger.exception(f"Failed to refresh Google token for user {user_id}")
            return None

    return creds


def check_scopes_covered(granted_scopes: list[str], required_scopes: list[str]) -> bool:
    """Check if all required scopes are covered by the granted scopes."""
    return set(required_scopes).issubset(set(granted_scopes))
