"""Agent-related helper functions."""

import json
import logging
import os

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import (
    Agent,
    AgentAction,
    AgentShare,
    Conversation,
    Document,
    DriveLink,
    NotionLink,
    Team,
    WeeklyRecapLog,
)

logger = logging.getLogger(__name__)

# --- Agent type helpers ---

_AGENT_TYPE_MODEL_MAP = {
    "recherche_live": ("PERPLEXITY_MODEL", "perplexity:sonar"),
    "visuel": (None, "imagen:imagen-3.0-generate-002"),
}
_DEFAULT_MODEL = ("MISTRAL_MODEL", "mistral:mistral-small-latest")

_AGENT_TYPE_PROVIDER_MAP = {
    "recherche_live": "perplexity",
    "visuel": "imagen",
}


def resolve_model_id(agent) -> str:
    """Return the model_id for an agent based on its type."""
    atype = getattr(agent, "type", "conversationnel")
    env_var, default = _AGENT_TYPE_MODEL_MAP.get(atype, _DEFAULT_MODEL)
    return os.getenv(env_var, default) if env_var else default


def resolve_llm_provider(agent_type: str) -> str:
    """Return the llm_provider string for an agent type."""
    return _AGENT_TYPE_PROVIDER_MAP.get(agent_type, "mistral")


def _user_can_access_agent(user_id: int, agent_id: int, db: Session):
    """Return the agent if the user is owner OR has an AgentShare. Otherwise raise 403."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.user_id == user_id:
        return agent
    share = db.query(AgentShare).filter(AgentShare.agent_id == agent_id, AgentShare.user_id == user_id).first()
    if share:
        return agent
    raise HTTPException(status_code=403, detail="Access denied to this agent")


def _user_can_edit_agent(user_id: int, agent_id: int, db: Session):
    """Return the agent if the user is owner OR has an AgentShare with can_edit=True. Otherwise raise 403."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.user_id == user_id:
        return agent
    share = (
        db.query(AgentShare)
        .filter(AgentShare.agent_id == agent_id, AgentShare.user_id == user_id, AgentShare.can_edit == True)
        .first()
    )
    if share:
        return agent
    raise HTTPException(status_code=403, detail="You do not have edit permission on this agent")


def _delete_agent_and_related_data(agent: Agent, owner_user_id: int, db: Session):
    """Delete an agent and all its related data (conversations, actions, teams, shares)."""
    agent_id = agent.id

    # Delete all agent shares
    db.query(AgentShare).filter(AgentShare.agent_id == agent_id).delete()
    db.flush()

    # Delete all conversations related to this agent
    conversations = db.query(Conversation).filter(Conversation.agent_id == agent_id).all()
    for conv in conversations:
        db.delete(conv)
    db.flush()

    # Delete all agent actions related to this agent
    actions = db.query(AgentAction).filter(AgentAction.agent_id == agent_id).all()
    for action in actions:
        db.delete(action)
    db.flush()

    # Check if this agent is used in any teams
    teams = db.query(Team).filter(Team.user_id == owner_user_id).all()
    teams_to_delete = []
    for team in teams:
        if team.leader_agent_id == agent_id:
            logger.warning(f"Agent {agent_id} is leader of team {team.id}, deleting team")
            teams_to_delete.append(team)
        else:
            try:
                action_ids = json.loads(team.action_agent_ids) if team.action_agent_ids else []
                if agent_id in action_ids:
                    action_ids = [aid for aid in action_ids if aid != agent_id]
                    team.action_agent_ids = json.dumps(action_ids)
                    db.add(team)
            except Exception as e:
                logger.error(f"Error updating team {team.id}: {e}")

    if teams_to_delete:
        team_ids = [team.id for team in teams_to_delete]

        ct_result = db.execute(
            text("SELECT id FROM conversations_teams WHERE team_id = ANY(:team_ids)"), {"team_ids": team_ids}
        )
        ct_ids = [row[0] for row in ct_result]

        if ct_ids:
            db.execute(text("DELETE FROM messages_teams WHERE conversation_id = ANY(:ct_ids)"), {"ct_ids": ct_ids})
            db.flush()
            db.execute(text("DELETE FROM conversations_teams WHERE id = ANY(:ct_ids)"), {"ct_ids": ct_ids})
            db.flush()

        conv_result = db.execute(
            text("SELECT id FROM conversations WHERE team_id = ANY(:team_ids)"), {"team_ids": team_ids}
        )
        conv_ids = [row[0] for row in conv_result]

        if conv_ids:
            db.execute(text("DELETE FROM messages WHERE conversation_id = ANY(:conv_ids)"), {"conv_ids": conv_ids})
            db.flush()

        db.execute(text("DELETE FROM conversations WHERE team_id = ANY(:team_ids)"), {"team_ids": team_ids})
        db.flush()

        db.execute(text("DELETE FROM teams WHERE id = ANY(:team_ids)"), {"team_ids": team_ids})
        db.flush()

    # Delete weekly recap logs
    db.query(WeeklyRecapLog).filter(WeeklyRecapLog.agent_id == agent_id).delete()
    db.flush()

    # Nullify notion_link_id on documents before deleting notion links
    db.query(Document).filter(Document.agent_id == agent_id, Document.notion_link_id.isnot(None)).update(
        {"notion_link_id": None}
    )
    db.flush()

    # Delete notion links
    db.query(NotionLink).filter(NotionLink.agent_id == agent_id).delete()
    db.flush()

    # Nullify drive_link_id on documents before deleting drive links
    db.query(Document).filter(Document.agent_id == agent_id, Document.drive_link_id.isnot(None)).update(
        {"drive_link_id": None}
    )
    db.flush()

    # Delete drive links
    db.query(DriveLink).filter(DriveLink.agent_id == agent_id).delete()
    db.flush()

    db.delete(agent)


def update_agent_embedding(agent, db):
    if agent.contexte:
        from mistral_embeddings import get_embedding as mistral_get_embedding

        agent.embedding = json.dumps(mistral_get_embedding(agent.contexte))
        db.commit()
