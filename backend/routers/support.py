"""Support-account endpoints: list companies + switch the active company.

Gated on User.is_support. The active company is carried as a JWT claim re-issued
by the switch endpoint; the tenant middleware enforces it (and re-checks is_support).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from auth import verify_token, create_access_token, ACCESS_TOKEN_MAX_AGE
from database import get_db, User, Company, SupportAuditLog

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_support(user_id: str, db: Session) -> User:
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not getattr(user, "is_support", False):
        raise HTTPException(status_code=403, detail="Support access required")
    return user


@router.get("/api/support/companies")
async def list_companies(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """List all companies (support only)."""
    _require_support(user_id, db)
    rows = db.query(Company.id, Company.name).order_by(Company.name.asc()).all()
    return {"companies": [{"id": cid, "name": name} for cid, name in rows]}


@router.post("/api/support/active-company")
async def set_active_company(
    request: Request, response: Response, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Switch the support session's active company (re-issues the token cookie)."""
    _require_support(user_id, db)
    body = await request.json()
    company_id = body.get("company_id")
    company = db.query(Company).filter(Company.id == company_id).first() if company_id is not None else None
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Re-issue the access-token cookie carrying the active company claim.
    token = create_access_token(data={"sub": str(user_id), "active_company_id": int(company.id)})
    response.set_cookie(
        key="token", value=token, httponly=True, secure=True, samesite="lax", max_age=ACCESS_TOKEN_MAX_AGE, path="/"
    )

    db.add(
        SupportAuditLog(
            support_user_id=int(user_id),
            target_company_id=int(company.id),
            method="SWITCH",
            path="/api/support/active-company",
        )
    )
    db.commit()
    logger.info(f"Support user {user_id} switched to company {company.id}")
    return {"active_company_id": company.id, "company_name": company.name}
