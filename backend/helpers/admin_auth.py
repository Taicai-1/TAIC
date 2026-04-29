"""Shared admin/scheduler authentication helper.

Used by both routine and monitoring endpoints to allow access
via admin JWT or Cloud Scheduler secret header.
"""

import os

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from auth import verify_token
from permissions import require_role

_SCHEDULER_SECRET = os.getenv("ROUTINE_SCHEDULER_SECRET", "")


def verify_admin_or_scheduler(request: Request, db: Session) -> bool:
    """Allow access if user is admin OR request has a valid scheduler secret."""
    # Check scheduler secret header first (Cloud Scheduler / MCP server)
    scheduler_header = request.headers.get("X-Scheduler-Secret", "")
    if _SCHEDULER_SECRET and scheduler_header == _SCHEDULER_SECRET:
        return True

    # Fall back to normal admin auth
    try:
        user_id = verify_token(request)
        require_role(int(user_id), db, "admin")
        return True
    except Exception:
        raise HTTPException(
            status_code=403,
            detail="Admin access or valid scheduler secret required",
        )
