"""Agent and Team CRUD endpoints, weekly recap endpoints."""

import os
import io
import json
import time
import hmac
import logging
import traceback
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from google.cloud import storage

from auth import verify_token
from database import (
    get_db,
    User,
    Agent,
    AgentShare,
    Team,
    TeamMember,
    Company,
)
from helpers.agent_helpers import (
    resolve_model_id,
    resolve_llm_provider,
    _user_can_access_agent,
    _user_can_edit_agent,
    _delete_agent_and_related_data,
    update_agent_embedding,
)
from helpers.tenant import _get_caller_company_id
from validation import (
    AgentCreateValidated,
    TeamCreateValidated,
    sanitize_filename,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _parse_enabled_plugins(raw: str) -> str | None:
    """Parse enabled_plugins from a JSON array string or CSV string.

    Returns a JSON-encoded list string, or None if input is empty/invalid.
    """
    if not raw:
        return None
    try:
        return json.dumps(json.loads(raw))
    except json.JSONDecodeError:
        return json.dumps([p.strip() for p in raw.split(",") if p.strip()])


@router.get("/api/agent-photo/{agent_id}")
async def get_agent_photo(agent_id: int, db: Session = Depends(get_db)):
    """Proxy endpoint to serve agent profile photos from GCS."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent or not agent.profile_photo:
        raise HTTPException(status_code=404, detail="No photo")

    photo_url = agent.profile_photo
    # If it's a GCS URL, download via service account and serve
    if photo_url.startswith("https://storage.googleapis.com/"):
        try:
            GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "applydi-agent-photos")
            blob_name = photo_url.split(f"{GCS_BUCKET_NAME}/", 1)[-1]
            client = storage.Client()
            bucket = client.bucket(GCS_BUCKET_NAME)
            blob = bucket.blob(blob_name)
            content = blob.download_as_bytes()
            content_type = blob.content_type or "image/jpeg"
            return Response(
                content=content,
                media_type=content_type,
                headers={"Cache-Control": "public, max-age=86400"},
            )
        except Exception:
            logger.exception(f"Failed to fetch agent photo from GCS for agent {agent_id}")
            raise HTTPException(status_code=404, detail="Photo not found in storage")

    raise HTTPException(status_code=404, detail="Invalid photo URL")


# Endpoints pour les agents
@router.get("/agents")
async def get_agents(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Get user's own agents + agents shared with them"""
    try:
        uid = int(user_id)
        own_agents = db.query(Agent).filter(Agent.user_id == uid).order_by(Agent.created_at.desc()).all()
        result = [
            {
                "id": a.id,
                "name": a.name,
                "type": a.type,
                "statut": a.statut,
                "profile_photo": a.profile_photo,
                "llm_provider": a.llm_provider,
                "neo4j_enabled": a.neo4j_enabled,
                "date_awareness_enabled": getattr(a, "date_awareness_enabled", False),
                "email_tags": a.email_tags,
                "weekly_recap_enabled": a.weekly_recap_enabled,
                "recap_frequency": a.recap_frequency,
                "recap_hour": a.recap_hour,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "shared": False,
            }
            for a in own_agents
        ]

        # Add agents shared with this user
        shared = (
            db.query(Agent, User, AgentShare)
            .join(AgentShare, AgentShare.agent_id == Agent.id)
            .join(User, Agent.user_id == User.id)
            .filter(AgentShare.user_id == uid)
            .order_by(Agent.created_at.desc())
            .all()
        )
        for a, owner, share in shared:
            result.append(
                {
                    "id": a.id,
                    "name": a.name,
                    "type": a.type,
                    "statut": a.statut,
                    "profile_photo": a.profile_photo,
                    "llm_provider": a.llm_provider,
                    "neo4j_enabled": a.neo4j_enabled,
                    "date_awareness_enabled": a.date_awareness_enabled,
                    "email_tags": a.email_tags,
                    "weekly_recap_enabled": a.weekly_recap_enabled,
                    "recap_frequency": a.recap_frequency,
                    "recap_hour": a.recap_hour,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    "shared": True,
                    "can_edit": share.can_edit,
                    "owner_username": owner.username,
                }
            )

        return {"agents": result}
    except Exception as e:
        logger.error(f"Error getting agents: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/agents")
async def create_agent(
    name: str = Form(...),
    contexte: str = Form(None),
    biographie: str = Form(None),
    type: str = Form("conversationnel"),
    email_tags: str = Form(None),  # JSON array ou liste séparée par virgules
    neo4j_enabled: str = Form("false"),
    neo4j_person_name: str = Form(None),
    neo4j_depth: str = Form("1"),
    weekly_recap_enabled: str = Form("false"),
    weekly_recap_prompt: str = Form(None),
    weekly_recap_recipients: str = Form(None),
    recap_frequency: str = Form("weekly"),
    recap_hour: str = Form("9"),
    date_awareness_enabled: str = Form("false"),
    enabled_plugins: str = Form(None),
    profile_photo: UploadFile = File(None),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Create a new agent with optional profile photo upload"""
    try:
        logger.info(
            f"[CREATE_AGENT] Champs reçus: name={name}, contexte={contexte}, biographie={biographie}, type={type}, profile_photo={profile_photo.filename if profile_photo else None}, user_id={user_id}"
        )
        # --- GCS UPLOAD UTILS ---
        GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "applydi-agent-photos")

        def upload_profile_photo_to_gcs(file: UploadFile) -> str:
            """Upload a file to Google Cloud Storage and return its public URL."""
            client = storage.Client()
            bucket = client.bucket(GCS_BUCKET_NAME)
            safe_name = sanitize_filename(file.filename)
            filename = f"{int(time.time())}_{safe_name}"
            blob = bucket.blob(filename)
            blob.upload_from_file(file.file, content_type=file.content_type)
            try:
                # Make the object publicly readable so the browser can load it directly
                blob.make_public()
            except Exception:
                logger.exception("Failed to make uploaded profile photo public; object may remain private")
            public_url = blob.public_url
            logger.info(f"Uploaded profile photo to GCS and set public URL: {public_url}")
            return public_url

        photo_url = None
        if profile_photo is not None:
            try:
                photo_url = upload_profile_photo_to_gcs(profile_photo)
                logger.info(f"[CREATE_AGENT] Photo de profil uploadée sur GCS: {photo_url}")
            except Exception as file_err:
                logger.error(f"[CREATE_AGENT] Erreur lors de l'upload GCS: {file_err}")
                raise HTTPException(status_code=500, detail="Erreur lors de l'upload de la photo")

        # Parser les email_tags
        parsed_email_tags = None
        if email_tags:
            try:
                # Essayer de parser comme JSON
                parsed_email_tags = json.loads(email_tags)
            except json.JSONDecodeError:
                # Sinon, traiter comme liste séparée par virgules
                tags_list = [t.strip() for t in email_tags.split(",") if t.strip()]
                # Normaliser avec @ prefix
                parsed_email_tags = [f"@{t.lstrip('@').lower()}" for t in tags_list]
            parsed_email_tags = json.dumps(parsed_email_tags) if parsed_email_tags else None

        # Parse enabled_plugins for actionnable agents
        parsed_plugins = _parse_enabled_plugins(enabled_plugins) if type == "actionnable" else None

        # Auto-calculate llm_provider from type
        effective_llm_provider = resolve_llm_provider(type)
        caller_company_id = _get_caller_company_id(user_id, db)
        db_agent = Agent(
            name=name,
            contexte=contexte,
            biographie=biographie,
            profile_photo=photo_url,
            statut="privé",
            type=type,
            llm_provider=effective_llm_provider,
            email_tags=parsed_email_tags,
            neo4j_enabled=neo4j_enabled.lower() in ("true", "1", "yes"),
            neo4j_person_name=neo4j_person_name if neo4j_person_name and neo4j_person_name.strip() else None,
            neo4j_depth=int(neo4j_depth) if neo4j_depth else 1,
            weekly_recap_enabled=weekly_recap_enabled.lower() in ("true", "1", "yes"),
            weekly_recap_prompt=weekly_recap_prompt if weekly_recap_prompt and weekly_recap_prompt.strip() else None,
            weekly_recap_recipients=weekly_recap_recipients
            if weekly_recap_recipients and weekly_recap_recipients.strip()
            else None,
            recap_frequency=recap_frequency if recap_frequency in ("daily", "weekly", "monthly") else "weekly",
            recap_hour=max(0, min(23, int(recap_hour))) if recap_hour.isdigit() else 9,
            date_awareness_enabled=date_awareness_enabled.lower() in ("true", "1", "yes"),
            enabled_plugins=parsed_plugins,
            user_id=int(user_id),
            company_id=caller_company_id,
        )
        db.add(db_agent)
        db.commit()
        db.refresh(db_agent)
        # Génère et stocke l'embedding si le contexte n'est pas vide
        if db_agent.contexte and db_agent.contexte.strip():
            update_agent_embedding(db_agent, db)
        logger.info(f"[CREATE_AGENT] Agent créé avec succès: id={db_agent.id}, statut={db_agent.statut}")
        return {"agent": db_agent}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CREATE_AGENT] Erreur inattendue: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de la création de l'agent")


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Delete an agent and all related data"""
    try:
        agent = db.query(Agent).filter(Agent.id == agent_id, Agent.user_id == int(user_id)).first()

        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        _delete_agent_and_related_data(agent, int(user_id), db)

        # Clean up slash_commands references in the agent's company
        user_company_id = _get_caller_company_id(user_id, db)
        if user_company_id:
            company = db.query(Company).filter(Company.id == user_company_id).first()
            if company and company.slash_commands:
                try:
                    commands = json.loads(company.slash_commands)
                    updated = False
                    for cmd in commands:
                        if agent_id in cmd.get("agent_ids", []):
                            cmd["agent_ids"] = [aid for aid in cmd["agent_ids"] if aid != agent_id]
                            updated = True
                    if updated:
                        company.slash_commands = json.dumps(commands)
                except (json.JSONDecodeError, TypeError):
                    pass

        db.commit()

        return {"message": "Agent deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting agent: {e}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Get a specific agent (owner or shared user)"""
    try:
        uid = int(user_id)
        agent = _user_can_access_agent(uid, agent_id, db)
        is_owner = agent.user_id == uid

        # Check can_edit for shared agents
        can_edit = False
        if not is_owner:
            share = db.query(AgentShare).filter(AgentShare.agent_id == agent_id, AgentShare.user_id == uid).first()
            can_edit = share.can_edit if share else False

        result = {
            "id": agent.id,
            "name": agent.name,
            "type": agent.type,
            "statut": agent.statut,
            "profile_photo": agent.profile_photo,
            "llm_provider": agent.llm_provider,
            "neo4j_enabled": agent.neo4j_enabled,
            "date_awareness_enabled": agent.date_awareness_enabled,
            "enabled_plugins": agent.enabled_plugins,
            "created_at": agent.created_at.isoformat() if agent.created_at else None,
            "shared": not is_owner,
            "can_edit": can_edit,
        }
        # Expose editable fields to owner OR shared user with can_edit
        if is_owner or can_edit:
            result.update(
                {
                    "contexte": agent.contexte,
                    "biographie": agent.biographie,
                    "neo4j_person_name": agent.neo4j_person_name,
                    "neo4j_depth": agent.neo4j_depth,
                    "email_tags": agent.email_tags,
                    "weekly_recap_enabled": agent.weekly_recap_enabled,
                    "weekly_recap_prompt": agent.weekly_recap_prompt,
                    "weekly_recap_recipients": agent.weekly_recap_recipients,
                    "recap_frequency": agent.recap_frequency,
                    "recap_hour": agent.recap_hour,
                }
            )
        if not is_owner:
            owner = db.query(User).filter(User.id == agent.user_id).first()
            result["owner_username"] = owner.username if owner else None

        return {"agent": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting agent: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/teams")
async def list_teams(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """List teams for the current user, including members."""
    try:
        teams = db.query(Team).filter(Team.user_id == int(user_id)).order_by(Team.created_at.desc()).all()
        team_ids = [t.id for t in teams]

        # Batch-load all members
        members_by_team = {}
        if team_ids:
            all_members = db.query(TeamMember).filter(TeamMember.team_id.in_(team_ids)).order_by(TeamMember.position).all()
            all_agent_ids = {m.agent_id for m in all_members}
            agent_lookup = {}
            if all_agent_ids:
                agents = db.query(Agent).filter(Agent.id.in_(all_agent_ids)).all()
                agent_lookup = {a.id: a for a in agents}

            for m in all_members:
                members_by_team.setdefault(m.team_id, []).append({
                    "agent_id": m.agent_id,
                    "role": m.role,
                    "name": agent_lookup[m.agent_id].name if m.agent_id in agent_lookup else None,
                    "specialization": m.specialization,
                    "auto_specialization": m.auto_specialization,
                    "position": m.position,
                })

        out = []
        for t in teams:
            t_members = members_by_team.get(t.id, [])
            leader = next((m for m in t_members if m["role"] == "leader"), None)
            action_members = [m for m in t_members if m["role"] == "member"]
            out.append({
                "id": t.id,
                "name": t.name,
                "contexte": t.contexte,
                "orchestration_prompt": t.orchestration_prompt,
                "members": t_members,
                # Legacy fields for backward compat
                "leader_agent_id": leader["agent_id"] if leader else t.leader_agent_id,
                "leader_name": leader["name"] if leader else None,
                "action_agent_ids": [m["agent_id"] for m in action_members],
                "action_agent_names": [m["name"] for m in action_members if m["name"]],
                "created_at": t.created_at.isoformat() if t.created_at else None,
            })
        return {"teams": out}
    except Exception as e:
        logger.exception(f"Error listing teams: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/teams")
async def create_team(
    payload: dict, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Create a team. Supports V2 (members array) and legacy (leader_agent_id) formats."""
    try:
        # Detect format
        is_v2 = "members" in payload

        if is_v2:
            from validation import TeamCreateV2Validated
            validated = TeamCreateV2Validated(**payload)
            name = validated.name
            contexte = validated.contexte
            orchestration_prompt = validated.orchestration_prompt
            members_data = validated.members
        else:
            from validation import TeamCreateValidated
            validated = TeamCreateValidated(**payload)
            name = validated.name
            contexte = validated.contexte
            orchestration_prompt = None
            # Convert legacy to V2 member format
            from validation import TeamMemberSchema
            members_data = [TeamMemberSchema(agent_id=validated.leader_agent_id, role="leader")]
            for aid in validated.action_agent_ids:
                members_data.append(TeamMemberSchema(agent_id=aid, role="member"))

        # Validate all agents belong to user and are conversationnel
        uid = int(user_id)
        for m in members_data:
            a = db.query(Agent).filter(Agent.id == m.agent_id, Agent.user_id == uid).first()
            if not a or getattr(a, "type", "conversationnel") != "conversationnel":
                raise HTTPException(
                    status_code=400,
                    detail=f"Agent {m.agent_id} doit etre un agent conversationnel appartenant a vous"
                )

        caller_company_id = _get_caller_company_id(user_id, db)
        leader_data = next(m for m in members_data if m.role == "leader")

        team = Team(
            name=name,
            contexte=contexte,
            orchestration_prompt=orchestration_prompt,
            leader_agent_id=leader_data.agent_id,
            action_agent_ids=json.dumps([m.agent_id for m in members_data if m.role == "member"]),
            user_id=uid,
            company_id=caller_company_id,
        )
        db.add(team)
        db.flush()

        # Create TeamMember entries
        for i, m in enumerate(members_data):
            tm = TeamMember(
                team_id=team.id,
                agent_id=m.agent_id,
                role=m.role,
                specialization=m.specialization,
                position=i,
                company_id=caller_company_id,
            )
            db.add(tm)

        db.commit()
        db.refresh(team)

        # Build response
        all_agent_ids = [m.agent_id for m in members_data]
        agents = db.query(Agent).filter(Agent.id.in_(all_agent_ids)).all()
        agent_lookup = {a.id: a.name for a in agents}

        resp_members = []
        for i, m in enumerate(members_data):
            resp_members.append({
                "agent_id": m.agent_id,
                "role": m.role,
                "name": agent_lookup.get(m.agent_id),
                "specialization": m.specialization,
                "position": i,
            })

        leader = next(m for m in resp_members if m["role"] == "leader")
        action_members = [m for m in resp_members if m["role"] == "member"]

        return {
            "team": {
                "id": team.id,
                "name": team.name,
                "contexte": team.contexte,
                "orchestration_prompt": team.orchestration_prompt,
                "members": resp_members,
                # Legacy compat
                "leader_agent_id": leader["agent_id"],
                "leader_name": leader["name"],
                "member_agent_ids": [m["agent_id"] for m in action_members],
                "member_agent_names": [m["name"] for m in action_members],
                "created_at": team.created_at.isoformat() if team.created_at else None,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error creating team: {e}")
        if 'relation "teams"' in str(e) or "does not exist" in str(e):
            raise HTTPException(status_code=500, detail="teams table not found in database.")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/teams/{team_id}")
async def get_team(team_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Get a single team with members."""
    try:
        t = db.query(Team).filter(Team.id == team_id, Team.user_id == int(user_id)).first()
        if not t:
            raise HTTPException(status_code=404, detail="Team not found")

        members = db.query(TeamMember).filter(TeamMember.team_id == t.id).order_by(TeamMember.position).all()
        agent_ids = {m.agent_id for m in members}
        agent_lookup = {}
        if agent_ids:
            agents = db.query(Agent).filter(Agent.id.in_(agent_ids)).all()
            agent_lookup = {a.id: a for a in agents}

        resp_members = []
        for m in members:
            a = agent_lookup.get(m.agent_id)
            resp_members.append({
                "agent_id": m.agent_id,
                "role": m.role,
                "name": a.name if a else None,
                "specialization": m.specialization,
                "auto_specialization": m.auto_specialization,
                "position": m.position,
            })

        leader = next((m for m in resp_members if m["role"] == "leader"), None)
        action_members = [m for m in resp_members if m["role"] == "member"]

        return {
            "team": {
                "id": t.id,
                "name": t.name,
                "contexte": t.contexte,
                "orchestration_prompt": t.orchestration_prompt,
                "members": resp_members,
                # Legacy compat
                "leader_agent_id": leader["agent_id"] if leader else t.leader_agent_id,
                "leader_name": leader["name"] if leader else None,
                "action_agent_ids": [m["agent_id"] for m in action_members],
                "action_agent_names": [m["name"] for m in action_members if m["name"]],
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching team {team_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/teams/suggest-specialization")
async def suggest_specialization_endpoint(
    payload: dict, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Auto-detect specialization for an agent."""
    from validation import SuggestSpecializationRequest
    validated = SuggestSpecializationRequest(**payload)

    agent = db.query(Agent).filter(Agent.id == validated.agent_id, Agent.user_id == int(user_id)).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    from database import Document
    docs = db.query(Document).filter(Document.agent_id == agent.id).limit(10).all()
    doc_names = [d.filename for d in docs if d.filename]

    from orchestrator import suggest_specialization
    spec = suggest_specialization(
        agent_name=agent.name,
        agent_contexte=agent.contexte or "",
        agent_biographie=agent.biographie or "",
        document_names=doc_names,
    )
    return {"specialization": spec}


@router.put("/teams/{team_id}/members")
async def update_team_members(
    team_id: int, payload: dict, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Replace full team composition."""
    from validation import TeamMemberSchema

    t = db.query(Team).filter(Team.id == team_id, Team.user_id == int(user_id)).first()
    if not t:
        raise HTTPException(status_code=404, detail="Team not found")

    members_raw = payload.get("members", [])
    members_data = [TeamMemberSchema(**m) for m in members_raw]

    # Validate
    leaders = [m for m in members_data if m.role == "leader"]
    if len(leaders) != 1:
        raise HTTPException(status_code=400, detail="Must have exactly one leader")
    non_leaders = [m for m in members_data if m.role == "member"]
    if len(non_leaders) < 1:
        raise HTTPException(status_code=400, detail="Must have at least one member")

    uid = int(user_id)
    for m in members_data:
        a = db.query(Agent).filter(Agent.id == m.agent_id, Agent.user_id == uid).first()
        if not a or getattr(a, "type", "conversationnel") != "conversationnel":
            raise HTTPException(status_code=400, detail=f"Agent {m.agent_id} invalid")

    # Delete old members
    db.query(TeamMember).filter(TeamMember.team_id == team_id).delete()

    caller_company_id = _get_caller_company_id(user_id, db)
    for i, m in enumerate(members_data):
        tm = TeamMember(
            team_id=team_id,
            agent_id=m.agent_id,
            role=m.role,
            specialization=m.specialization,
            position=i,
            company_id=caller_company_id,
        )
        db.add(tm)

    # Update legacy fields on Team
    leader = next(m for m in members_data if m.role == "leader")
    t.leader_agent_id = leader.agent_id
    t.action_agent_ids = json.dumps([m.agent_id for m in members_data if m.role == "member"])

    db.commit()
    return {"status": "ok"}


@router.patch("/teams/{team_id}/members/{agent_id}")
async def patch_team_member(
    team_id: int, agent_id: int, payload: dict,
    user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Update specialization or position of a team member."""
    t = db.query(Team).filter(Team.id == team_id, Team.user_id == int(user_id)).first()
    if not t:
        raise HTTPException(status_code=404, detail="Team not found")

    member = db.query(TeamMember).filter(
        TeamMember.team_id == team_id, TeamMember.agent_id == agent_id
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    if "specialization" in payload:
        member.specialization = payload["specialization"]
    if "position" in payload:
        member.position = payload["position"]

    db.commit()
    return {"status": "ok"}


# Endpoint pour modifier un agent existant
@router.put("/agents/{agent_id}")
async def update_agent(
    agent_id: int,
    name: str = Form(...),
    contexte: str = Form(None),
    biographie: str = Form(None),
    type: str = Form("conversationnel"),
    email_tags: str = Form(None),  # JSON array ou liste séparée par virgules
    neo4j_enabled: str = Form("false"),
    neo4j_person_name: str = Form(None),
    neo4j_depth: str = Form("1"),
    weekly_recap_enabled: str = Form("false"),
    weekly_recap_prompt: str = Form(None),
    weekly_recap_recipients: str = Form(None),
    recap_frequency: str = Form("weekly"),
    recap_hour: str = Form("9"),
    date_awareness_enabled: str = Form("false"),
    enabled_plugins: str = Form(None),
    profile_photo: UploadFile = File(None),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Met à jour un agent existant, y compris la photo de profil (GCS), le statut et les email_tags."""
    try:
        agent = _user_can_edit_agent(int(user_id), agent_id, db)

        agent.name = name
        agent.contexte = contexte
        agent.biographie = biographie
        agent.statut = "privé"
        agent.type = type
        agent.llm_provider = resolve_llm_provider(type)

        # Update enabled_plugins for actionnable agents
        if enabled_plugins is not None:
            agent.enabled_plugins = _parse_enabled_plugins(enabled_plugins) if agent.type == "actionnable" else None

        # Parser et mettre à jour les email_tags
        if email_tags is not None:
            if email_tags == "" or email_tags == "[]":
                agent.email_tags = None
            else:
                try:
                    parsed_tags = json.loads(email_tags)
                except json.JSONDecodeError:
                    tags_list = [t.strip() for t in email_tags.split(",") if t.strip()]
                    parsed_tags = [f"@{t.lstrip('@').lower()}" for t in tags_list]
                agent.email_tags = json.dumps(parsed_tags) if parsed_tags else None

        # Update Neo4j fields
        agent.neo4j_enabled = neo4j_enabled.lower() in ("true", "1", "yes")
        agent.neo4j_person_name = neo4j_person_name if neo4j_person_name and neo4j_person_name.strip() else None
        agent.neo4j_depth = int(neo4j_depth) if neo4j_depth else 1

        # Update Weekly Recap
        agent.weekly_recap_enabled = weekly_recap_enabled.lower() in ("true", "1", "yes")
        agent.weekly_recap_prompt = weekly_recap_prompt if weekly_recap_prompt and weekly_recap_prompt.strip() else None
        agent.weekly_recap_recipients = (
            weekly_recap_recipients if weekly_recap_recipients and weekly_recap_recipients.strip() else None
        )
        agent.recap_frequency = recap_frequency if recap_frequency in ("daily", "weekly", "monthly") else "weekly"
        agent.recap_hour = max(0, min(23, int(recap_hour))) if recap_hour.isdigit() else 9

        # Update Date Awareness
        agent.date_awareness_enabled = date_awareness_enabled.lower() in ("true", "1", "yes")

        GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "applydi-agent-photos")

        def upload_profile_photo_to_gcs(file: UploadFile) -> str:
            client = storage.Client()
            bucket = client.bucket(GCS_BUCKET_NAME)
            safe_name = sanitize_filename(file.filename)
            filename = f"{int(time.time())}_{safe_name}"
            blob = bucket.blob(filename)
            blob.upload_from_file(file.file, content_type=file.content_type)
            try:
                blob.make_public()
            except Exception:
                logger.exception("Failed to make uploaded profile photo public; object may remain private")
            public_url = blob.public_url
            logger.info(f"Uploaded profile photo to GCS and set public URL: {public_url}")
            return public_url

        if profile_photo is not None:
            try:
                photo_url = upload_profile_photo_to_gcs(profile_photo)
                agent.profile_photo = photo_url
            except Exception as file_err:
                logger.error(f"[UPDATE_AGENT] Erreur lors de l'upload GCS: {file_err}")
                raise HTTPException(status_code=500, detail="Erreur lors de l'upload de la photo")

        db.commit()
        db.refresh(agent)
        logger.info(f"[UPDATE_AGENT] Agent modifié avec succès: id={agent.id}, statut={agent.statut}")
        return {"agent": agent}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[UPDATE_AGENT] Erreur inattendue: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de la mise à jour de l'agent")


## ---- Weekly Recap Endpoints ----


@router.post("/api/weekly-recap/trigger")
async def trigger_weekly_recap(request: Request, db: Session = Depends(get_db)):
    """Trigger weekly recap for all due agents. Protected by X-API-Key.
    Designed to be called every hour by Cloud Scheduler.
    Checks each agent's recap_frequency and recap_hour before sending."""
    api_key = request.headers.get("X-API-Key", "")
    expected_key = os.getenv("WEEKLY_RECAP_API_KEY", "")

    if not expected_key:
        raise HTTPException(status_code=500, detail="WEEKLY_RECAP_API_KEY not configured")
    if not api_key or not hmac.compare_digest(api_key, expected_key):
        raise HTTPException(status_code=401, detail="Invalid API Key")

    from weekly_recap import process_agent_recap, process_recap
    from recap_scheduler import _is_due, _is_recap_due, PARIS_TZ
    from sqlalchemy import text

    db.execute(text("SET LOCAL app.service_bypass = 'true'"))

    now = datetime.now(PARIS_TZ)

    # Process new Recap entities
    from database import Recap

    recaps = db.query(Recap).filter(Recap.enabled == True).all()
    results = []
    skipped = 0
    for recap in recaps:
        if not _is_recap_due(recap, now, db):
            skipped += 1
            continue
        result = process_recap(recap, db)
        results.append({"recap_id": recap.id, "recap_name": recap.name, **result})

    # Legacy agents without Recap entities
    agents = db.query(Agent).filter(Agent.weekly_recap_enabled == True).all()
    for agent in agents:
        has_recaps = db.query(Recap).filter(Recap.agent_id == agent.id).count() > 0
        if has_recaps:
            skipped += 1
            continue
        if not _is_due(agent, now, db):
            skipped += 1
            continue
        result = process_agent_recap(agent, db)
        results.append({"agent_id": agent.id, "agent_name": agent.name, **result})

    return {"processed": len(results), "skipped": skipped, "results": results}


@router.post("/api/agents/{agent_id}/recap-preview")
async def recap_preview(agent_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Generate a recap preview without sending email. Auth required."""
    agent = db.query(Agent).filter(Agent.id == agent_id, Agent.user_id == int(user_id)).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Redirect to first Recap entity if one exists
    from database import Recap

    first_recap = db.query(Recap).filter(Recap.agent_id == agent_id).order_by(Recap.created_at.asc()).first()
    if first_recap:
        from routers.recaps import recap_preview as _recap_preview

        return await _recap_preview(first_recap.id, user_id, db)

    from weekly_recap import (
        fetch_weekly_messages,
        fetch_traceability_documents,
        fetch_notion_content,
        build_recap_prompt,
        generate_recap_html,
        get_model_id_for_agent,
        get_days_back,
    )
    from openai_client import get_chat_response as _get_chat_response

    days_back = get_days_back(agent)
    freq = getattr(agent, "recap_frequency", "weekly")
    messages = fetch_weekly_messages(agent.id, db, days_back=days_back)
    docs = fetch_traceability_documents(agent.id, db, days_back=days_back)
    notion_pages = fetch_notion_content(agent.id, db)

    if not messages and not docs and not notion_pages:
        return {"status": "no_data", "message": "No messages or documents for this period", "html": None}

    prompt_messages = build_recap_prompt(agent, messages, docs, notion_pages, frequency=freq)
    model_id = get_model_id_for_agent(agent)
    recap_content = _get_chat_response(prompt_messages, model_id=model_id)
    html = generate_recap_html(agent.name, recap_content)

    return {
        "status": "success",
        "html": html,
        "message_count": len(messages),
        "doc_count": len(docs),
        "notion_count": len(notion_pages),
    }


@router.post("/api/agents/{agent_id}/recap-send")
async def recap_send(agent_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Send recap email now for a specific agent. Auth required."""
    agent = db.query(Agent).filter(Agent.id == agent_id, Agent.user_id == int(user_id)).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Redirect to first Recap entity if one exists
    from database import Recap

    first_recap = db.query(Recap).filter(Recap.agent_id == agent_id).order_by(Recap.created_at.asc()).first()
    if first_recap:
        from routers.recaps import recap_send as _recap_send

        return await _recap_send(first_recap.id, user_id, db)

    if not agent.weekly_recap_enabled:
        raise HTTPException(status_code=400, detail="Weekly recap is not enabled for this agent")

    from weekly_recap import process_agent_recap

    result = process_agent_recap(agent, db)
    return result


class ImproveContextRequest(BaseModel):
    contexte: str | None = None


@router.post("/api/agents/{agent_id}/improve-context")
async def improve_agent_context(
    agent_id: int,
    body: ImproveContextRequest = ImproveContextRequest(),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Use Mistral AI to improve the agent's context prompt via prompt engineering."""
    agent = db.query(Agent).filter(Agent.id == agent_id, Agent.user_id == int(user_id)).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Use contexte from request body if provided, otherwise fall back to DB
    contexte = (body.contexte or "").strip() if body.contexte else (agent.contexte or "").strip()

    if not contexte:
        raise HTTPException(status_code=400, detail="Agent has no context to improve")

    from mistral_client import generate_text

    prompt = (
        "Tu es un expert en prompt engineering. Ta tâche est de RÉÉCRIRE le prompt système ci-dessous "
        "pour un chatbot RAG, en le rendant plus efficace.\n\n"
        "RÈGLES ABSOLUES :\n"
        "- CONSERVE TOUS les détails spécifiques : noms de personnes, entreprises, rôles, domaines, expertise mentionnés\n"
        "- NE GÉNÈRE JAMAIS de placeholders comme [préciser], [domaine], [nom], etc.\n"
        "- NE REMPLACE PAS le contenu par un template générique\n"
        "- Le résultat doit être une version AMÉLIORÉE du texte original, PAS un nouveau texte\n"
        "- Garde la même langue que l'original\n\n"
        "AMÉLIORATIONS À APPORTER :\n"
        "- Reformule pour que les instructions soient plus claires et directes\n"
        "- Ajoute des précisions sur le ton et le style de réponse adaptés au rôle décrit\n"
        "- Ajoute une instruction pour s'appuyer sur les documents fournis quand disponibles\n"
        "- Ajoute une instruction courte sur quoi faire si la question est hors périmètre\n"
        "- Reste concis (pas plus de 2x la longueur originale)\n\n"
        "PROMPT ORIGINAL À AMÉLIORER :\n"
        "---\n"
        f"{contexte}\n"
        "---\n\n"
        "Retourne UNIQUEMENT le prompt amélioré. Aucun commentaire, aucune explication, aucun guillemet englobant."
    )

    try:
        improved = generate_text(prompt, model_name="mistral-large-latest", temperature=0.4, max_tokens=4000)
        return {"original": contexte, "improved": improved.strip()}
    except Exception as e:
        logger.error(f"Failed to improve context for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to improve context")
