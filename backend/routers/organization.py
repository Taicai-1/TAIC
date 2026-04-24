"""Organization endpoints: company CRUD, members, invitations, integrations, agent sharing, slash commands, neo4j."""

import json
import logging
import os
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from auth import verify_token, hash_password, create_access_token
from database import (
    get_db,
    User,
    Agent,
    AgentShare,
    Company,
    CompanyCreationRequest,
    CompanyMembership,
    CompanyInvitation,
)
from email_service import (
    send_invitation_email,
    send_agent_share_email,
    send_agent_unshare_email,
    send_agent_share_updated_email,
)
from helpers.agent_helpers import _delete_agent_and_related_data
from helpers.rate_limiting import _check_org_request_rate_limit
from helpers.tenant import _get_caller_company_id
from permissions import require_role, get_user_membership
from redis_client import get_cached_user, invalidate_user_cache
from schemas.organization import SlashCommandItem

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/api/companies/request")
async def create_company_request(
    request: Request,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Submit a request to create a new organization. Requires manual approval."""
    import secrets as _secrets
    from validation import CompanyRequestCreateValidated
    from email_service import send_email, render_admin_org_request_email

    # Rate limit by IP
    client_ip = request.client.host if request.client else "unknown"
    if not _check_org_request_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Trop de demandes, réessayez dans une heure",
        )

    # Parse + validate body
    body = await request.json()
    try:
        validated = CompanyRequestCreateValidated(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    name = validated.name

    uid = int(user_id)

    # User must not already be in an org
    if db.query(CompanyMembership).filter(CompanyMembership.user_id == uid).first():
        raise HTTPException(
            status_code=409,
            detail="Vous êtes déjà membre d'une organisation",
        )

    # User must not already have a pending request
    existing_pending = (
        db.query(CompanyCreationRequest)
        .filter(
            CompanyCreationRequest.user_id == uid,
            CompanyCreationRequest.status == "pending",
        )
        .first()
    )
    if existing_pending:
        raise HTTPException(
            status_code=409,
            detail="Une demande est déjà en cours d'examen",
        )

    # Create the request
    token = _secrets.token_urlsafe(48)
    req = CompanyCreationRequest(
        user_id=uid,
        requested_name=name,
        status="pending",
        token=token,
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    # Fetch requester info for the email
    user = db.query(User).filter(User.id == uid).first()
    requester_email = user.email if user else "inconnu"

    # Build magic links
    approve_url = f"{BACKEND_PUBLIC_URL}/api/admin/companies/request/{token}?action=approve"
    reject_url = f"{BACKEND_PUBLIC_URL}/api/admin/companies/request/{token}?action=reject"

    # Send admin email (best-effort — don't fail the request if SMTP is down)
    try:
        html = render_admin_org_request_email(
            requester_email=requester_email,
            requested_name=name,
            approve_url=approve_url,
            reject_url=reject_url,
        )
        send_email(
            to=ADMIN_NOTIFICATION_EMAIL,
            subject=f'🏢 Nouvelle demande : "{name}" par {requester_email}',
            html_body=html,
        )
    except Exception as e:
        logger.error(f"Failed to send admin notification for org request {req.id}: {e}")

    return {
        "status": "pending",
        "requested_name": name,
    }


@router.get("/api/companies/request/mine")
async def get_my_company_request(
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Return the user's most recent org creation request (or null)."""
    uid = int(user_id)
    req = (
        db.query(CompanyCreationRequest)
        .filter(CompanyCreationRequest.user_id == uid)
        .order_by(CompanyCreationRequest.created_at.desc())
        .first()
    )
    if not req:
        return {"request": None}
    return {
        "request": {
            "id": req.id,
            "requested_name": req.requested_name,
            "status": req.status,
            "created_at": req.created_at.isoformat() if req.created_at else None,
            "decided_at": req.decided_at.isoformat() if req.decided_at else None,
            "decided_reason": req.decided_reason,
        }
    }


from fastapi.responses import HTMLResponse


@router.get("/api/admin/companies/request/{token}", response_class=HTMLResponse)
async def admin_org_request_confirm_page(
    token: str,
    action: str,
    db: Session = Depends(get_db),
):
    """Admin confirmation page (rendered HTML). No auth: token IS the auth.

    Shows a confirmation button to avoid accidental actions from Gmail pre-fetch.
    """
    from admin_html_pages import (
        confirm_approve_page,
        confirm_reject_page,
        error_page,
    )

    if action not in ("approve", "reject"):
        return HTMLResponse(error_page("Action inconnue."), status_code=400)

    req = db.query(CompanyCreationRequest).filter(CompanyCreationRequest.token == token).first()
    if not req:
        return HTMLResponse(error_page("Cette demande n'existe pas."), status_code=404)

    if req.status != "pending":
        return HTMLResponse(
            error_page(f"Cette demande a déjà été traitée (statut : {req.status})."),
            status_code=410,
        )

    user = db.query(User).filter(User.id == req.user_id).first()
    requester_email = user.email if user else "inconnu"

    post_url = f"{BACKEND_PUBLIC_URL}/api/admin/companies/request/{token}/decide"

    if action == "approve":
        return HTMLResponse(confirm_approve_page(token, requester_email, req.requested_name, post_url))
    else:
        return HTMLResponse(confirm_reject_page(token, requester_email, req.requested_name, post_url))


@router.post("/api/admin/companies/request/{token}/decide", response_class=HTMLResponse)
async def admin_org_request_decide(
    token: str,
    action: str = Form(...),
    reason: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Execute the admin decision (approve/reject). No auth: token is the auth."""
    import secrets as _secrets
    from admin_html_pages import success_page, error_page
    from email_service import (
        send_email,
        render_user_org_approved_email,
        render_user_org_rejected_email,
    )

    if action not in ("approve", "reject"):
        return HTMLResponse(error_page("Action inconnue."), status_code=400)

    req = db.query(CompanyCreationRequest).filter(CompanyCreationRequest.token == token).first()
    if not req:
        return HTMLResponse(error_page("Cette demande n'existe pas."), status_code=404)

    if req.status != "pending":
        return HTMLResponse(
            error_page(f"Cette demande a déjà été traitée (statut : {req.status})."),
            status_code=410,
        )

    user = db.query(User).filter(User.id == req.user_id).first()
    if not user:
        req.status = "rejected"
        req.decided_at = datetime.utcnow()
        req.decided_reason = "Utilisateur introuvable"
        db.commit()
        return HTMLResponse(error_page("Utilisateur introuvable — demande annulée."), status_code=404)

    user_app_url = f"{FRONTEND_PUBLIC_URL}/organization"

    if action == "approve":
        # Re-check name uniqueness at approval time (race condition with other orgs)
        if db.query(Company).filter(Company.name == req.requested_name).first():
            return HTMLResponse(
                error_page(
                    f'Le nom "{req.requested_name}" est déjà pris. Refusez cette demande ou contactez le demandeur.'
                ),
                status_code=409,
            )

        # Re-check user is not already in an org
        if db.query(CompanyMembership).filter(CompanyMembership.user_id == user.id).first():
            return HTMLResponse(
                error_page("L'utilisateur a rejoint une autre organisation entre-temps."),
                status_code=409,
            )

        # Create company + membership
        company = Company(
            name=req.requested_name,
            neo4j_enabled=True,
            invite_code=_secrets.token_urlsafe(16),
        )
        db.add(company)
        db.flush()

        membership = CompanyMembership(
            user_id=user.id,
            company_id=company.id,
            role="owner",
        )
        db.add(membership)

        # Also sync user.company_id (existing pattern in the codebase)
        user.company_id = company.id

        req.status = "approved"
        req.decided_at = datetime.utcnow()
        req.company_id = company.id
        db.commit()

        # Invalidate user cache (consistent with other user mutations)
        try:
            invalidate_user_cache(user.id)
        except Exception as e:
            logger.error(f"Failed to invalidate user cache: {e}")

        # Send approval email
        try:
            html = render_user_org_approved_email(req.requested_name, user_app_url)
            send_email(
                to=user.email,
                subject=f'✅ Votre organisation "{req.requested_name}" a été approuvée',
                html_body=html,
            )
        except Exception as e:
            logger.error(f"Failed to send approval email: {e}")

        return HTMLResponse(success_page(f'L\'organisation "{req.requested_name}" a été créée pour {user.email}.'))

    else:  # reject
        cleaned_reason = (reason or "").strip() or None
        req.status = "rejected"
        req.decided_at = datetime.utcnow()
        req.decided_reason = cleaned_reason
        db.commit()

        try:
            html = render_user_org_rejected_email(req.requested_name, cleaned_reason, user_app_url)
            send_email(
                to=user.email,
                subject="Votre demande d'organisation",
                html_body=html,
            )
        except Exception as e:
            logger.error(f"Failed to send rejection email: {e}")

        return HTMLResponse(success_page(f'La demande pour "{req.requested_name}" a été refusée.'))


@router.get("/api/companies/mine")
async def get_my_company(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Get the current user's company with role and integration status."""
    uid = int(user_id)
    membership = db.query(CompanyMembership).filter(CompanyMembership.user_id == uid).first()
    if not membership:
        return {"company": None}

    company = db.query(Company).filter(Company.id == membership.company_id).first()
    if not company:
        return {"company": None}

    result = {
        "id": company.id,
        "name": company.name,
        "neo4j_enabled": company.neo4j_enabled,
        "role": membership.role,
        "has_neo4j": bool(company._neo4j_uri),
        "has_notion": bool(company._notion_api_key),
    }
    # Include invite_code for admin/owner
    if membership.role in ("admin", "owner"):
        result["invite_code"] = company.invite_code
        result["invite_code_enabled"] = company.invite_code_enabled

    return {"company": result}


@router.put("/api/user/company")
async def affiliate_user_to_company(
    request: Request, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Affiliate user to an existing company by name."""
    body = await request.json()
    company_name = body.get("company_name", "").strip()
    if not company_name:
        raise HTTPException(status_code=400, detail="Le paramètre 'company_name' est requis")

    company = db.query(Company).filter(Company.name == company_name).first()
    if not company:
        raise HTTPException(status_code=404, detail="Organisation introuvable")

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.company_id = company.id
    db.commit()
    invalidate_user_cache(user.id)

    return {"company": {"id": company.id, "name": company.name, "neo4j_enabled": company.neo4j_enabled}}


# ============================================================================
# ORGANIZATION MANAGEMENT ENDPOINTS
# ============================================================================


@router.post("/api/companies/invite")
async def invite_to_company(request: Request, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Send an email invitation to join the organization. Requires admin+."""
    import secrets as _secrets
    from permissions import require_role

    membership = require_role(int(user_id), db, "admin")
    body = await request.json()
    email = body.get("email", "").strip().lower()
    role = body.get("role", "member")

    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    if role not in ("member", "admin"):
        raise HTTPException(status_code=400, detail="Role must be 'member' or 'admin'")

    # Check if user with this email is already a member
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        existing_m = (
            db.query(CompanyMembership)
            .filter(
                CompanyMembership.user_id == existing_user.id, CompanyMembership.company_id == membership.company_id
            )
            .first()
        )
        if existing_m:
            raise HTTPException(status_code=409, detail="This user is already a member of the organization")

    # Check for pending invitation
    pending = (
        db.query(CompanyInvitation)
        .filter(
            CompanyInvitation.company_id == membership.company_id,
            CompanyInvitation.email == email,
            CompanyInvitation.status == "pending",
        )
        .first()
    )
    if pending:
        if pending.expires_at < datetime.utcnow():
            db.delete(pending)
            db.flush()
        else:
            raise HTTPException(status_code=409, detail="An invitation is already pending for this email")

    token = _secrets.token_urlsafe(48)
    invitation = CompanyInvitation(
        company_id=membership.company_id,
        email=email,
        role=role,
        token=token,
        invited_by_user_id=int(user_id),
        expires_at=datetime.utcnow() + timedelta(hours=24),
    )
    db.add(invitation)
    db.commit()

    # Send invitation email
    company = db.query(Company).filter(Company.id == membership.company_id).first()
    try:
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
        join_link = f"{frontend_url}/join?token={token}"
        send_invitation_email(email, company.name, join_link)
    except Exception as e:
        logger.warning(f"Failed to send invitation email to {email}: {e}")

    return {"message": "Invitation sent", "token": token}


@router.post("/api/companies/join")
async def join_company(request: Request, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Join an organization via invite token (email) or invite_code (shareable link)."""
    import secrets as _secrets

    uid = int(user_id)
    body = await request.json()
    token = body.get("token", "").strip()
    invite_code = body.get("invite_code", "").strip()

    # Check user isn't already in an org
    existing = db.query(CompanyMembership).filter(CompanyMembership.user_id == uid).first()
    if existing:
        raise HTTPException(status_code=409, detail="You are already a member of an organization")

    user = db.query(User).filter(User.id == uid).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if token:
        # Join via email invitation token
        invitation = (
            db.query(CompanyInvitation)
            .filter(CompanyInvitation.token == token, CompanyInvitation.status == "pending")
            .first()
        )
        if not invitation:
            raise HTTPException(status_code=404, detail="Invalid or expired invitation")
        if invitation.expires_at < datetime.utcnow():
            invitation.status = "expired"
            db.commit()
            raise HTTPException(status_code=410, detail="This invitation has expired")

        company_id = invitation.company_id
        role = invitation.role
        invitation.status = "accepted"

    elif invite_code:
        # Join via shareable invite code
        company = (
            db.query(Company).filter(Company.invite_code == invite_code, Company.invite_code_enabled == True).first()
        )
        if not company:
            raise HTTPException(status_code=404, detail="Invalid invite code")
        company_id = company.id
        role = "member"

    else:
        raise HTTPException(status_code=400, detail="Either 'token' or 'invite_code' is required")

    user.company_id = company_id
    membership = CompanyMembership(user_id=uid, company_id=company_id, role=role)
    db.add(membership)
    db.commit()
    invalidate_user_cache(uid)

    company = db.query(Company).filter(Company.id == company_id).first()
    return {
        "message": f"You have joined {company.name}",
        "company": {"id": company.id, "name": company.name, "role": role},
    }


@router.post("/api/companies/invite-code/regenerate")
async def regenerate_invite_code(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Regenerate the shareable invite code. Owner only."""
    import secrets as _secrets
    from permissions import require_role

    membership = require_role(int(user_id), db, "owner")
    company = db.query(Company).filter(Company.id == membership.company_id).first()
    company.invite_code = _secrets.token_urlsafe(16)
    db.commit()

    return {"invite_code": company.invite_code}


@router.put("/api/companies/invite-code/toggle")
async def toggle_invite_code(request: Request, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Enable or disable the shareable invite code. Owner only."""
    from permissions import require_role

    membership = require_role(int(user_id), db, "owner")
    body = await request.json()
    enabled = body.get("enabled", True)

    company = db.query(Company).filter(Company.id == membership.company_id).first()
    company.invite_code_enabled = bool(enabled)
    db.commit()

    return {"invite_code_enabled": company.invite_code_enabled}


@router.get("/api/companies/members")
async def list_company_members(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """List all members of the organization. Requires admin+."""
    from permissions import require_role
    from sqlalchemy import func

    membership = require_role(int(user_id), db, "admin")

    members = (
        db.query(CompanyMembership, User)
        .join(User, CompanyMembership.user_id == User.id)
        .filter(CompanyMembership.company_id == membership.company_id)
        .order_by(CompanyMembership.joined_at.asc())
        .all()
    )

    result = []
    for m, u in members:
        agent_count = db.query(Agent).filter(Agent.user_id == u.id).count()
        result.append(
            {
                "id": m.id,
                "user_id": u.id,
                "username": u.username,
                "email": u.email,
                "role": m.role,
                "joined_at": m.joined_at.isoformat() if m.joined_at else None,
                "agent_count": agent_count,
            }
        )

    return {"members": result}


@router.put("/api/companies/members/{member_id}/role")
async def update_member_role(
    member_id: int, request: Request, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Change a member's role. Owner only."""
    from permissions import require_role

    membership = require_role(int(user_id), db, "owner")
    body = await request.json()
    new_role = body.get("role", "")

    if new_role not in ("member", "admin"):
        raise HTTPException(status_code=400, detail="Role must be 'member' or 'admin'")

    target = (
        db.query(CompanyMembership)
        .filter(CompanyMembership.id == member_id, CompanyMembership.company_id == membership.company_id)
        .first()
    )
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    if target.role == "owner":
        raise HTTPException(status_code=403, detail="Cannot change the owner's role")

    target.role = new_role
    db.commit()

    return {"message": f"Role updated to {new_role}"}


@router.delete("/api/companies/members/{member_id}")
async def remove_member(member_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Remove a member from the organization. Requires admin+."""
    from permissions import require_role

    membership = require_role(int(user_id), db, "admin")
    target = (
        db.query(CompanyMembership)
        .filter(CompanyMembership.id == member_id, CompanyMembership.company_id == membership.company_id)
        .first()
    )
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    if target.role == "owner":
        raise HTTPException(status_code=403, detail="Cannot remove the owner")

    # Clean up agent shares for the departing user
    db.query(AgentShare).filter(AgentShare.user_id == target.user_id).delete()

    # Remove the company_id from the user record too
    user = db.query(User).filter(User.id == target.user_id).first()
    if user:
        user.company_id = None

    db.delete(target)
    db.commit()
    invalidate_user_cache(target.user_id)

    return {"message": "Member removed"}


@router.post("/api/companies/leave")
async def leave_company(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Leave the current organization. Owner cannot leave."""
    from permissions import get_user_membership

    uid = int(user_id)
    membership = get_user_membership(uid, db)
    if not membership:
        raise HTTPException(status_code=404, detail="You are not a member of any organization")

    if membership.role == "owner":
        raise HTTPException(
            status_code=403,
            detail="Owner cannot leave the organization. Transfer ownership first or delete the organization.",
        )

    # Clean up agent shares for the departing user
    db.query(AgentShare).filter(AgentShare.user_id == uid).delete()

    user = db.query(User).filter(User.id == uid).first()
    if user:
        user.company_id = None

    db.delete(membership)
    db.commit()
    invalidate_user_cache(uid)

    return {"message": "You have left the organization"}


@router.delete("/api/companies")
async def delete_company(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Delete the organization. Owner only. Does not delete user accounts."""
    from permissions import require_role

    membership = require_role(int(user_id), db, "owner")
    company_id = membership.company_id
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Collect member user IDs for cache invalidation
    member_ids = [
        m.user_id for m in db.query(CompanyMembership).filter(CompanyMembership.company_id == company_id).all()
    ]

    # RLS WITH CHECK blocks writing company_id = NULL.
    # Use a raw connection to temporarily DISABLE RLS, do all cleanup, then re-enable.
    rls_tables = [
        "agents",
        "agent_shares",
        "documents",
        "document_chunks",
        "conversations",
        "messages",
        "teams",
        "notion_links",
        "weekly_recap_logs",
        "agent_actions",
    ]

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()

        # Disable RLS and drop NOT NULL on company_id for all tenant-scoped tables
        for table in rls_tables:
            cur.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
            cur.execute(f"ALTER TABLE {table} ALTER COLUMN company_id DROP NOT NULL")

        # Delete org-specific junction data
        cur.execute("DELETE FROM agent_shares WHERE company_id = %s", (company_id,))
        cur.execute("DELETE FROM company_invitations WHERE company_id = %s", (company_id,))
        cur.execute("DELETE FROM company_memberships WHERE company_id = %s", (company_id,))

        # Nullify company_id on all tenant-scoped tables
        for table in rls_tables:
            cur.execute(f"UPDATE {table} SET company_id = NULL WHERE company_id = %s", (company_id,))

        # Dissociate users and delete the company
        cur.execute("UPDATE users SET company_id = NULL WHERE company_id = %s", (company_id,))
        cur.execute("DELETE FROM companies WHERE id = %s", (company_id,))

        # Re-enable RLS (NOT NULL stays dropped — aligns with SQLAlchemy model nullable=True)
        for table in rls_tables:
            cur.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            cur.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()

    # Invalidate cache for all former members
    for uid in member_ids:
        invalidate_user_cache(uid)

    return {"message": "Organization deleted"}


@router.put("/api/companies/integrations")
async def update_company_integrations(
    request: Request, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Configure org-level integration credentials. Owner only."""
    from permissions import require_role

    membership = require_role(int(user_id), db, "owner")
    company = db.query(Company).filter(Company.id == membership.company_id).first()
    body = await request.json()

    # Neo4j
    if "neo4j_uri" in body:
        company.org_neo4j_uri = body["neo4j_uri"] or None
    if "neo4j_user" in body:
        company.org_neo4j_user = body["neo4j_user"] or None
    if "neo4j_password" in body:
        company.org_neo4j_password = body["neo4j_password"] or None

    # Notion
    if "notion_api_key" in body:
        company.org_notion_api_key = body["notion_api_key"] or None

    db.commit()
    return {"message": "Integrations updated"}


@router.get("/api/companies/integrations")
async def get_company_integrations(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Get the integration status (without secrets). Owner only."""
    from permissions import require_role

    membership = require_role(int(user_id), db, "owner")
    company = db.query(Company).filter(Company.id == membership.company_id).first()

    return {
        "neo4j": {
            "configured": bool(company._neo4j_uri),
            "uri": company.org_neo4j_uri[:30] + "..." if company._neo4j_uri else None,
            "user": company.org_neo4j_user if company._neo4j_user else None,
        },
        "notion": {
            "configured": bool(company._notion_api_key),
            "key_preview": company.org_notion_api_key[:8] + "..." if company._notion_api_key else None,
        },
    }


@router.get("/api/companies/agents")
async def list_company_agents(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """List all agents in the organization. Requires admin+."""
    from permissions import require_role

    membership = require_role(int(user_id), db, "admin")

    # Get all user IDs in this company
    member_ids = [
        m.user_id
        for m in db.query(CompanyMembership).filter(CompanyMembership.company_id == membership.company_id).all()
    ]

    agents = (
        db.query(Agent, User)
        .join(User, Agent.user_id == User.id)
        .filter(Agent.user_id.in_(member_ids))
        .order_by(Agent.created_at.desc())
        .all()
    )

    result = []
    for agent, owner in agents:
        doc_count = db.query(Document).filter(Document.agent_id == agent.id).count()
        share_count = db.query(AgentShare).filter(AgentShare.agent_id == agent.id).count()
        result.append(
            {
                "id": agent.id,
                "name": agent.name,
                "type": agent.type,
                "statut": agent.statut,
                "llm_provider": agent.llm_provider,
                "owner_username": owner.username,
                "owner_id": owner.id,
                "created_at": agent.created_at.isoformat() if agent.created_at else None,
                "document_count": doc_count,
                "shared_with_count": share_count,
            }
        )

    return {"agents": result}


@router.delete("/api/companies/agents/{agent_id}")
async def delete_company_agent(agent_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Delete an agent from the organization. Requires admin+."""
    from permissions import require_role

    membership = require_role(int(user_id), db, "admin")

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Verify the agent owner is a member of the same company
    owner_membership = (
        db.query(CompanyMembership)
        .filter(CompanyMembership.user_id == agent.user_id, CompanyMembership.company_id == membership.company_id)
        .first()
    )
    if not owner_membership:
        raise HTTPException(status_code=404, detail="Agent not found in this organization")

    try:
        _delete_agent_and_related_data(agent, agent.user_id, db)
        db.commit()
        return {"message": "Agent deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting org agent: {e}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/api/companies/agents/{agent_id}/share")
async def share_agent(
    agent_id: int, request: Request, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Share an agent with another user in the same org. Owner of agent or admin+ required."""
    from permissions import require_role, get_user_membership

    uid = int(user_id)
    body = await request.json()
    target_user_id = body.get("user_id")
    can_edit = bool(body.get("can_edit", False))
    if not target_user_id:
        raise HTTPException(status_code=422, detail="user_id is required")

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Check permission: owner of the agent OR admin+
    is_owner = agent.user_id == uid
    if not is_owner:
        require_role(uid, db, "admin")

    # Both users must be in the same org
    caller_membership = get_user_membership(uid, db)
    if not caller_membership:
        raise HTTPException(status_code=403, detail="You are not in an organization")

    target_membership = (
        db.query(CompanyMembership)
        .filter(
            CompanyMembership.user_id == target_user_id, CompanyMembership.company_id == caller_membership.company_id
        )
        .first()
    )
    if not target_membership:
        raise HTTPException(status_code=404, detail="Target user not found in this organization")

    # Cannot share with the owner of the agent
    if target_user_id == agent.user_id:
        raise HTTPException(status_code=400, detail="Cannot share an agent with its owner")

    # Check if already shared
    existing = (
        db.query(AgentShare).filter(AgentShare.agent_id == agent_id, AgentShare.user_id == target_user_id).first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Agent already shared with this user")

    share = AgentShare(
        agent_id=agent_id,
        user_id=target_user_id,
        shared_by_user_id=uid,
        can_edit=can_edit,
        company_id=agent.company_id,
    )
    db.add(share)
    db.commit()

    # Notify the recipient by email (non-blocking: share succeeds even if email fails)
    try:
        target_user = db.query(User).filter(User.id == target_user_id).first()
        sharer_user = db.query(User).filter(User.id == uid).first()
        if target_user and sharer_user:
            frontend_url = os.getenv("FRONTEND_URL", "https://taic.ai")
            chat_link = f"{frontend_url}/chat/{agent_id}"
            send_agent_share_email(target_user.email, sharer_user.username, agent.name, can_edit, chat_link)
            logger.info(f"Share notification email sent to {target_user.email} for agent {agent_id}")
    except Exception as e:
        logger.warning(f"Failed to send share notification email for agent {agent_id}: {e}")

    return {"message": "Agent shared successfully"}


@router.delete("/api/companies/agents/{agent_id}/share/{target_user_id}")
async def unshare_agent(
    agent_id: int, target_user_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Remove a share. Owner of agent, admin+, or the target user themselves."""
    from permissions import require_role, get_user_membership

    uid = int(user_id)

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    is_owner = agent.user_id == uid
    is_self = target_user_id == uid

    if not is_owner and not is_self:
        require_role(uid, db, "admin")

    share = db.query(AgentShare).filter(AgentShare.agent_id == agent_id, AgentShare.user_id == target_user_id).first()
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")

    db.delete(share)
    db.commit()

    # Notify the target user by email, unless they removed themselves
    if not is_self:
        try:
            target_user = db.query(User).filter(User.id == target_user_id).first()
            sharer_user = db.query(User).filter(User.id == uid).first()
            if target_user and sharer_user:
                send_agent_unshare_email(target_user.email, sharer_user.username, agent.name)
                logger.info(f"Unshare notification email sent to {target_user.email} for agent {agent_id}")
        except Exception as e:
            logger.warning(f"Failed to send unshare notification email for agent {agent_id}: {e}")

    return {"message": "Share removed"}


@router.put("/api/companies/agents/{agent_id}/share/{target_user_id}")
async def update_agent_share(
    agent_id: int,
    target_user_id: int,
    request: Request,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Update can_edit permission on a share. Owner of agent or admin+ required."""
    from permissions import require_role

    uid = int(user_id)

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    is_owner = agent.user_id == uid
    if not is_owner:
        require_role(uid, db, "admin")

    share = db.query(AgentShare).filter(AgentShare.agent_id == agent_id, AgentShare.user_id == target_user_id).first()
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")

    body = await request.json()
    permission_changed = False
    if "can_edit" in body:
        new_can_edit = bool(body["can_edit"])
        if new_can_edit != share.can_edit:
            share.can_edit = new_can_edit
            permission_changed = True
    db.commit()

    # Notify target user only when the permission actually changed
    if permission_changed:
        try:
            target_user = db.query(User).filter(User.id == target_user_id).first()
            sharer_user = db.query(User).filter(User.id == uid).first()
            if target_user and sharer_user:
                frontend_url = os.getenv("FRONTEND_URL", "https://taic.ai")
                chat_link = f"{frontend_url}/chat/{agent_id}"
                send_agent_share_updated_email(
                    target_user.email, sharer_user.username, agent.name, share.can_edit, chat_link
                )
                logger.info(f"Permission change notification email sent to {target_user.email} for agent {agent_id}")
        except Exception as e:
            logger.warning(f"Failed to send permission change notification email for agent {agent_id}: {e}")

    return {"message": "Share updated", "can_edit": share.can_edit}


@router.get("/api/companies/agents/{agent_id}/shares")
async def list_agent_shares(agent_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """List users an agent is shared with. Owner of agent or admin+ required."""
    from permissions import require_role, get_user_membership

    uid = int(user_id)

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    is_owner = agent.user_id == uid
    if not is_owner:
        require_role(uid, db, "admin")

    shares = (
        db.query(AgentShare, User)
        .join(User, AgentShare.user_id == User.id)
        .filter(AgentShare.agent_id == agent_id)
        .all()
    )

    return {
        "shares": [
            {
                "user_id": u.id,
                "username": u.username,
                "email": u.email,
                "can_edit": s.can_edit,
                "shared_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s, u in shares
        ]
    }


@router.get("/api/companies/slash-commands")
async def get_slash_commands(
    agent_id: Optional[int] = None,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Get slash commands for the caller's company. Optional agent_id filter."""
    company_id = _get_caller_company_id(user_id, db)
    if not company_id:
        raise HTTPException(status_code=404, detail="No company found")
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    commands = json.loads(company.slash_commands) if company.slash_commands else []
    if agent_id is not None:
        commands = [c for c in commands if agent_id in c.get("agent_ids", [])]
    return {"slash_commands": commands}


@router.put("/api/companies/slash-commands")
async def update_slash_commands(
    request: Request,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Replace all slash commands for the caller's company. Owner/admin only."""
    company_id = _get_caller_company_id(user_id, db)
    if not company_id:
        raise HTTPException(status_code=404, detail="No company found")

    # Check role - use CompanyMembership model
    membership = (
        db.query(CompanyMembership)
        .filter(CompanyMembership.company_id == company_id, CompanyMembership.user_id == int(user_id))
        .first()
    )
    if not membership or membership.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Owner or admin required")

    body = await request.json()
    items = body if isinstance(body, list) else body.get("slash_commands", [])

    # Validate each item
    seen_commands = set()
    validated = []
    for item in items:
        sc = SlashCommandItem(**item)
        if sc.command in seen_commands:
            raise HTTPException(status_code=400, detail=f"Duplicate command: {sc.command}")
        seen_commands.add(sc.command)

        # Validate agent_ids exist
        for aid in sc.agent_ids:
            agent = db.query(Agent).filter(Agent.id == aid).first()
            if not agent:
                raise HTTPException(status_code=400, detail=f"Agent {aid} not found")

        validated.append(
            {
                "id": sc.id or str(uuid4()),
                "command": sc.command,
                "prompt": sc.prompt,
                "agent_ids": sc.agent_ids,
            }
        )

    company = db.query(Company).filter(Company.id == company_id).first()
    company.slash_commands = json.dumps(validated)
    db.commit()

    return {"slash_commands": validated}


@router.get("/api/neo4j/persons")
async def list_neo4j_persons(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """List Person nodes from Neo4j for the user's company."""
    user = get_cached_user(user_id, db)
    if not user or not user.company_id:
        return {"persons": []}

    try:
        from neo4j_client import get_persons_for_company

        persons = get_persons_for_company(user.company_id)
        return {"persons": persons}
    except Exception as e:
        logger.warning(f"Failed to list Neo4j persons: {e}")
        return {"persons": []}

