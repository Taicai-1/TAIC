"""Shared admin/scheduler authentication helper.

Used by both routine and monitoring endpoints to allow access
via the platform support account OR a Cloud Scheduler secret header.
The admin area is reserved for the support account (``is_support``);
ordinary company admins/owners are not granted access.
"""

import os

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from auth import verify_token
from database import User

_SCHEDULER_SECRET = os.getenv("ROUTINE_SCHEDULER_SECRET", "").strip()


def verify_admin_or_scheduler(request: Request, db: Session) -> bool:
    """Allow access if user is the platform support account OR request has a valid scheduler secret."""
    # Check scheduler secret header first (Cloud Scheduler / MCP server)
    scheduler_header = request.headers.get("X-Scheduler-Secret", "")
    if _SCHEDULER_SECRET and scheduler_header == _SCHEDULER_SECRET:
        return True

    # Fall back to support-account auth: the admin area is support-only.
    try:
        user_id = verify_token(request)
        user = db.query(User).filter(User.id == int(user_id)).first()
        is_support = bool(getattr(user, "is_support", False)) if user else False
    except Exception:
        is_support = False

    if is_support:
        return True

    raise HTTPException(
        status_code=403,
        detail="Support access or valid scheduler secret required",
    )
