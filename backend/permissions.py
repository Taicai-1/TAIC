"""
Organization role-based permissions.

Role hierarchy: owner > admin > member
"""

import logging
from typing import Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session

from database import CompanyMembership

logger = logging.getLogger(__name__)

ROLE_HIERARCHY = {"owner": 3, "admin": 2, "member": 1}


def get_user_membership(user_id: int, db: Session) -> Optional[CompanyMembership]:
    """Return the user's CompanyMembership or None."""
    return db.query(CompanyMembership).filter(CompanyMembership.user_id == user_id).first()


def require_role(user_id: int, db: Session, min_role: str = "member") -> CompanyMembership:
    """Verify the user has at least `min_role` in their organization.
    Raises 403 if insufficient, 404 if no membership."""
    membership = get_user_membership(user_id, db)
    if not membership:
        raise HTTPException(status_code=404, detail="You are not a member of any organization")

    user_level = ROLE_HIERARCHY.get(membership.role, 0)
    required_level = ROLE_HIERARCHY.get(min_role, 0)

    if user_level < required_level:
        raise HTTPException(status_code=403, detail=f"Requires at least '{min_role}' role")

    return membership
