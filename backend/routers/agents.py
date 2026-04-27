"""Agent and Team CRUD endpoints, weekly recap endpoints."""

import os
import io
import json
import time
import hmac
import logging
import traceback

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Response
from sqlalchemy.orm import Session
from google.cloud import storage

from auth import verify_token
from database import (
    get_db,
    User,
    Agent,
    AgentShare,
    Team,
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
                "email_tags": a.email_tags,
                "weekly_recap_enabled": a.weekly_recap_enabled,
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
                    "email_tags": a.email_tags,
                    "weekly_recap_enabled": a.weekly_recap_enabled,
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
    """List teams for the current user."""
    try:
        teams = db.query(Team).filter(Team.user_id == int(user_id)).order_by(Team.created_at.desc()).all()

        # Batch-load all referenced agent IDs across all teams (avoids N+1)
        all_agent_ids = set()
        for t in teams:
            all_agent_ids.add(t.leader_agent_id)
            try:
                ids = json.loads(t.action_agent_ids) if t.action_agent_ids else []
                all_agent_ids.update(int(aid) for aid in ids)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        agent_lookup = {}
        if all_agent_ids:
            agents = db.query(Agent).filter(Agent.id.in_(all_agent_ids)).all()
            agent_lookup = {a.id: a.name for a in agents}

        out = []
        for t in teams:
            leader_name = agent_lookup.get(t.leader_agent_id)
            action_ids = []
            action_agent_names = []
            try:
                action_ids = json.loads(t.action_agent_ids) if t.action_agent_ids else []
                action_agent_names = [agent_lookup[int(aid)] for aid in action_ids if int(aid) in agent_lookup]
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

            out.append(
                {
                    "id": t.id,
                    "name": t.name,
                    "contexte": t.contexte,
                    "leader_agent_id": t.leader_agent_id,
                    "leader_name": leader_name,
                    "action_agent_ids": action_ids,
                    "action_agent_names": action_agent_names,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
            )
        return {"teams": out}
    except Exception as e:
        logger.exception(f"Error listing teams: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/teams")
async def create_team(
    payload: TeamCreateValidated, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Create a team. Expected payload: {name, contexte (opt), leader_agent_id, action_agent_ids: [id,id,id]}"""
    try:
        name = payload.name
        contexte = payload.contexte
        leader_agent_id = payload.leader_agent_id
        member_agent_ids = payload.action_agent_ids
        # On accepte n'importe quel nombre d'agents

        # Valider le chef (doit être conversationnel)
        leader = db.query(Agent).filter(Agent.id == int(leader_agent_id), Agent.user_id == int(user_id)).first()
        if not leader or getattr(leader, "type", "conversationnel") != "conversationnel":
            raise HTTPException(status_code=400, detail="Leader agent must be a conversationnel agent belonging to you")

        # Valider les membres (uniquement conversationnels)
        member_agents = []
        for aid in member_agent_ids:
            a = db.query(Agent).filter(Agent.id == int(aid), Agent.user_id == int(user_id)).first()
            if not a or getattr(a, "type", "") != "conversationnel":
                raise HTTPException(
                    status_code=400, detail=f"Agent {aid} doit être un agent conversationnel appartenant à vous"
                )
            member_agents.append(a)

        team = Team(
            name=name,
            contexte=contexte,
            leader_agent_id=int(leader_agent_id),
            action_agent_ids=json.dumps([int(x) for x in member_agent_ids]),
            user_id=int(user_id),
            company_id=_get_caller_company_id(user_id, db),
        )
        db.add(team)
        db.commit()
        db.refresh(team)

        # Préparer la réponse avec les noms
        resp = {
            "team": {
                "id": team.id,
                "name": team.name,
                "contexte": team.contexte,
                "leader_agent_id": team.leader_agent_id,
                "leader_name": leader.name,
                "member_agent_ids": [int(x) for x in member_agent_ids],
                "member_agent_names": [a.name for a in member_agents],
                "created_at": team.created_at.isoformat() if team.created_at else None,
            }
        }
        return resp
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error creating team: {e}")
        # If the teams table does not exist, provide a helpful message
        if 'relation "teams"' in str(e) or "does not exist" in str(e):
            raise HTTPException(
                status_code=500,
                detail="teams table not found in database. Please create the table before using this endpoint.",
            )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/teams/{team_id}")
async def get_team(team_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    try:
        t = db.query(Team).filter(Team.id == team_id, Team.user_id == int(user_id)).first()
        if not t:
            raise HTTPException(status_code=404, detail="Team not found")

        # Batch-load leader + action agents in one query (avoids N+1)
        all_agent_ids = {t.leader_agent_id}
        action_ids = []
        try:
            action_ids = json.loads(t.action_agent_ids) if t.action_agent_ids else []
            all_agent_ids.update(int(aid) for aid in action_ids)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        agent_lookup = {}
        if all_agent_ids:
            agents = db.query(Agent).filter(Agent.id.in_(all_agent_ids)).all()
            agent_lookup = {a.id: a.name for a in agents}

        leader_name = agent_lookup.get(t.leader_agent_id)
        action_agent_names = [agent_lookup[int(aid)] for aid in action_ids if int(aid) in agent_lookup]

        return {
            "team": {
                "id": t.id,
                "name": t.name,
                "contexte": t.contexte,
                "leader_agent_id": t.leader_agent_id,
                "leader_name": leader_name,
                "action_agent_ids": action_ids,
                "action_agent_names": action_agent_names,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching team {team_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


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
        agent.llm_provider = "perplexity" if type == "recherche_live" else "mistral"

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
    """Trigger weekly recap for all enabled agents. Protected by X-API-Key."""
    api_key = request.headers.get("X-API-Key", "")
    expected_key = os.getenv("WEEKLY_RECAP_API_KEY", "")

    if not expected_key:
        raise HTTPException(status_code=500, detail="WEEKLY_RECAP_API_KEY not configured")
    if not api_key or not hmac.compare_digest(api_key, expected_key):
        raise HTTPException(status_code=401, detail="Invalid API Key")

    from weekly_recap import process_agent_recap

    agents = db.query(Agent).filter(Agent.weekly_recap_enabled == True).all()
    results = []
    for agent in agents:
        result = process_agent_recap(agent, db)
        results.append({"agent_id": agent.id, "agent_name": agent.name, **result})

    return {"processed": len(results), "results": results}


@router.post("/api/agents/{agent_id}/recap-preview")
async def recap_preview(agent_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Generate a recap preview without sending email. Auth required."""
    agent = db.query(Agent).filter(Agent.id == agent_id, Agent.user_id == int(user_id)).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    from weekly_recap import (
        fetch_weekly_messages,
        fetch_traceability_documents,
        fetch_notion_content,
        build_recap_prompt,
        generate_recap_html,
        get_model_id_for_agent,
    )
    from openai_client import get_chat_response as _get_chat_response

    messages = fetch_weekly_messages(agent.id, db)
    docs = fetch_traceability_documents(agent.id, db)
    notion_pages = fetch_notion_content(agent.id, db)

    if not messages and not docs and not notion_pages:
        return {"status": "no_data", "message": "No messages or documents this week", "html": None}

    prompt_messages = build_recap_prompt(agent, messages, docs, notion_pages)
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
    if not agent.weekly_recap_enabled:
        raise HTTPException(status_code=400, detail="Weekly recap is not enabled for this agent")

    from weekly_recap import process_agent_recap

    result = process_agent_recap(agent, db)
    return result
