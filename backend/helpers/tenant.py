"""Tenant isolation helpers."""

from typing import Optional

from sqlalchemy.orm import Session

from redis_client import get_cached_user


def _get_caller_company_id(user_id, db: Session) -> Optional[int]:
    """Resolve the company_id for the current caller.

    Honors a support account's active company (set by the tenant middleware in the
    request contextvar); falls back to the user's own company for non-request
    contexts (e.g. background jobs). For normal users the active value equals their
    own company, so behavior is unchanged.
    """
    from database import get_current_company_id

    active = get_current_company_id()
    if active is not None:
        return active
    user = get_cached_user(user_id, db)
    return user.company_id if user else None
