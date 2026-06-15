"""Missions automation endpoints: CRUD, planning parse/events, documents, recaps, chat."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import verify_token
from database import Agent, Mission, MissionRecap, get_db
from permissions import require_role
from schemas.missions import MissionCreate, MissionUpdate

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_FILE_SIZE = 25 * 1024 * 1024
ALLOWED_EXT = (".pdf", ".txt", ".csv", ".docx", ".xlsx", ".pptx", ".json")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _get_mission_or_404(mission_id: int, user_id: int, company_id: int, db: Session) -> Mission:
    """Fetch a mission scoped to its creator + company (private to creator)."""
    mission = (
        db.query(Mission)
        .filter(Mission.id == mission_id, Mission.company_id == company_id, Mission.user_id == user_id)
        .first()
    )
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return mission


def _validate_agent(agent_id, company_id: int, db: Session):
    """Verify the companion belongs to the company; return it or None."""
    if agent_id is None:
        return None
    agent = db.query(Agent).filter(Agent.id == agent_id, Agent.company_id == company_id).first()
    if not agent:
        raise HTTPException(status_code=400, detail="Companion introuvable dans votre organisation")
    return agent


def _mission_detail(mission: Mission, db: Session) -> dict:
    last_recap = (
        db.query(MissionRecap)
        .filter(MissionRecap.mission_id == mission.id)
        .order_by(MissionRecap.created_at.desc())
        .first()
    )
    return {
        "id": mission.id,
        "name": mission.name,
        "objective": mission.objective,
        "agent_id": mission.agent_id,
        "status": mission.status,
        "recap_enabled": mission.recap_enabled,
        "recap_weekday": mission.recap_weekday,
        "recap_hour": mission.recap_hour,
        "created_at": mission.created_at.isoformat() if mission.created_at else None,
        "last_recap_at": last_recap.created_at.isoformat() if last_recap and last_recap.created_at else None,
    }


# --------------------------------------------------------------------------- #
# Mission CRUD
# --------------------------------------------------------------------------- #


@router.get("/api/automations/missions")
async def list_missions(user_id: int = Depends(verify_token), db: Session = Depends(get_db)):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    missions = (
        db.query(Mission)
        .filter(Mission.company_id == membership.company_id, Mission.user_id == user_id)
        .order_by(Mission.created_at.desc())
        .all()
    )
    return {"missions": [_mission_detail(m, db) for m in missions]}


@router.post("/api/automations/missions")
async def create_mission(
    body: MissionCreate, user_id: int = Depends(verify_token), db: Session = Depends(get_db)
):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    _validate_agent(body.agent_id, membership.company_id, db)

    mission = Mission(
        company_id=membership.company_id,
        user_id=user_id,
        agent_id=body.agent_id,
        name=body.name.strip(),
        objective=body.objective.strip(),
        recap_enabled=body.recap_enabled,
        recap_weekday=body.recap_weekday,
        recap_hour=body.recap_hour,
    )
    db.add(mission)
    db.commit()
    db.refresh(mission)
    return {"mission": _mission_detail(mission, db)}


@router.get("/api/automations/missions/{mission_id}")
async def get_mission(mission_id: int, user_id: int = Depends(verify_token), db: Session = Depends(get_db)):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    mission = _get_mission_or_404(mission_id, user_id, membership.company_id, db)
    return {"mission": _mission_detail(mission, db)}


@router.put("/api/automations/missions/{mission_id}")
async def update_mission(
    mission_id: int, body: MissionUpdate, user_id: int = Depends(verify_token), db: Session = Depends(get_db)
):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    mission = _get_mission_or_404(mission_id, user_id, membership.company_id, db)
    _validate_agent(body.agent_id, membership.company_id, db)

    mission.name = body.name.strip()
    mission.objective = body.objective.strip()
    mission.agent_id = body.agent_id
    mission.status = body.status
    mission.recap_enabled = body.recap_enabled
    mission.recap_weekday = body.recap_weekday
    mission.recap_hour = body.recap_hour
    mission.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(mission)
    return {"mission": _mission_detail(mission, db)}


@router.delete("/api/automations/missions/{mission_id}")
async def delete_mission(mission_id: int, user_id: int = Depends(verify_token), db: Session = Depends(get_db)):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    mission = _get_mission_or_404(mission_id, user_id, membership.company_id, db)
    db.delete(mission)
    db.commit()
    return {"success": True}
