"""Conversation-related helper functions."""

import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database import Agent, AgentShare, Conversation, Team

logger = logging.getLogger(__name__)


def verify_conversation_owner(conversation_id: int, user_id: str, db: Session) -> Conversation:
    """Load a conversation and verify the authenticated user owns it (via agent, share, or team)."""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    uid = int(user_id)
    # If the conversation has a user_id, check it matches
    if conv.user_id and conv.user_id == uid:
        return conv
    if conv.agent_id:
        agent = db.query(Agent).filter(Agent.id == conv.agent_id).first()
        if not agent:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if agent.user_id == uid:
            return conv
        # Check if user has a share on this agent
        share = db.query(AgentShare).filter(AgentShare.agent_id == conv.agent_id, AgentShare.user_id == uid).first()
        if share:
            return conv
        raise HTTPException(status_code=404, detail="Conversation not found")
    elif conv.team_id:
        team = db.query(Team).filter(Team.id == conv.team_id).first()
        if not team or team.user_id != uid:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv
