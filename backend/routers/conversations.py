"""Conversation endpoints: CRUD conversations, messages, feedback, title."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import List

from auth import verify_token
from database import get_db, Agent, AgentShare, Team, Conversation, Message
from helpers.agent_helpers import _user_can_access_agent
from helpers.tenant import _get_caller_company_id
from schemas.conversations import ConversationCreate, MessageCreate, MessageFeedbackRequest
from validation import ConversationTitleValidated

logger = logging.getLogger(__name__)
router = APIRouter()


def _verify_conversation_owner(conversation_id: int, user_id: str, db: Session) -> Conversation:
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


@router.post("/conversations", response_model=dict)
async def create_conversation(
    conv: ConversationCreate, db: Session = Depends(get_db), user_id: str = Depends(verify_token)
):
    uid = int(user_id)
    if conv.agent_id:
        _user_can_access_agent(uid, conv.agent_id, db)
    if conv.team_id:
        team = db.query(Team).filter(Team.id == conv.team_id).first()
        if not team or team.user_id != uid:
            raise HTTPException(status_code=404, detail="Team not found")
    conversation = Conversation(
        agent_id=conv.agent_id,
        team_id=conv.team_id,
        title=conv.title,
        user_id=uid,
        company_id=_get_caller_company_id(user_id, db),
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return {"conversation_id": conversation.id}


@router.get("/conversations", response_model=List[dict])
async def list_conversations(
    agent_id: int = Query(None),
    team_id: int = Query(None),
    db: Session = Depends(get_db),
    user_id: str = Depends(verify_token),
):
    uid = int(user_id)
    if agent_id is not None:
        agent = _user_can_access_agent(uid, agent_id, db)

        # Show user's own conversations + legacy conversations (no user_id) if user is owner
        user_filter = [Conversation.user_id == uid]
        if agent.user_id == uid:
            user_filter.append(Conversation.user_id.is_(None))
        conversations = (
            db.query(Conversation)
            .filter(Conversation.agent_id == agent_id, or_(*user_filter))
            .order_by(Conversation.created_at.desc())
            .all()
        )
    elif team_id is not None:
        team = db.query(Team).filter(Team.id == team_id).first()
        if not team or team.user_id != uid:
            raise HTTPException(status_code=404, detail="Team not found")
        conversations = (
            db.query(Conversation)
            .filter(Conversation.team_id == team_id)
            .order_by(Conversation.created_at.desc())
            .all()
        )
    else:
        raise HTTPException(status_code=422, detail="agent_id ou team_id doit être fourni")
    return [{"id": c.id, "title": c.title, "created_at": c.created_at} for c in conversations]


@router.post("/conversations/{conversation_id}/messages", response_model=dict)
async def add_message(
    conversation_id: int, msg: MessageCreate, db: Session = Depends(get_db), user_id: str = Depends(verify_token)
):
    _verify_conversation_owner(conversation_id, user_id, db)
    message = Message(
        conversation_id=conversation_id,
        role=msg.role,
        content=msg.content,
        company_id=_get_caller_company_id(user_id, db),
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return {"message_id": message.id}


@router.get("/conversations/{conversation_id}/messages", response_model=List[dict])
async def get_messages(conversation_id: int, db: Session = Depends(get_db), user_id: str = Depends(verify_token)):
    _verify_conversation_owner(conversation_id, user_id, db)
    messages = (
        db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.timestamp.asc()).all()
    )
    return [{"id": m.id, "role": m.role, "content": m.content, "timestamp": m.timestamp} for m in messages]


@router.patch("/messages/{message_id}/feedback")
async def set_message_feedback(
    message_id: int, req: MessageFeedbackRequest, db: Session = Depends(get_db), user_id: str = Depends(verify_token)
):
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    # Verify ownership via the message's conversation
    _verify_conversation_owner(msg.conversation_id, user_id, db)
    if req.feedback not in ("like", "dislike"):
        raise HTTPException(status_code=400, detail="Feedback must be 'like' or 'dislike'")
    msg.feedback = req.feedback
    # Si feedback = like, bufferise le message et le message user précédent
    if req.feedback == "like":
        msg.buffered = 1
        # Cherche le message user juste avant dans la même conversation
        prev_user_msg = (
            db.query(Message)
            .filter(
                Message.conversation_id == msg.conversation_id,
                Message.timestamp < msg.timestamp,
                Message.role == "user",
            )
            .order_by(Message.timestamp.desc())
            .first()
        )
        if prev_user_msg:
            prev_user_msg.feedback = "like"
            prev_user_msg.buffered = 1
    db.commit()
    return {"message_id": msg.id, "feedback": msg.feedback, "buffered": msg.buffered}


@router.put("/conversations/{conversation_id}/title")
async def update_conversation_title(
    conversation_id: int,
    data: ConversationTitleValidated,
    db: Session = Depends(get_db),
    user_id: str = Depends(verify_token),
):
    conv = _verify_conversation_owner(conversation_id, user_id, db)
    conv.title = data.title
    db.commit()
    db.refresh(conv)
    return {"id": conv.id, "title": conv.title}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int, db: Session = Depends(get_db), user_id: str = Depends(verify_token)
):
    conv = _verify_conversation_owner(conversation_id, user_id, db)
    db.delete(conv)
    db.commit()
    return {"message": "Conversation deleted"}
