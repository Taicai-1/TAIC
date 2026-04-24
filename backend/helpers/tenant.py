"""Tenant isolation helpers."""

from typing import Optional

from sqlalchemy.orm import Session

from redis_client import get_cached_user


def _get_caller_company_id(user_id, db: Session) -> Optional[int]:
    """Resolve the company_id for a user. Returns None for legacy users without an org."""
    user = get_cached_user(user_id, db)
    return user.company_id if user else None
