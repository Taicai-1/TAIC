"""User account endpoints: change-password, export-data, stats, delete-account."""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from auth import verify_token, verify_password, hash_password
from database import get_db, User, Agent, Document, Conversation, Message, Team, PasswordResetToken
from helpers.rate_limiting import _check_password_change_rate_limit
from redis_client import get_cached_user, invalidate_user_cache
from validation import ChangePasswordRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/user/change-password")
async def change_password(
    request: Request, body: ChangePasswordRequest, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Change the authenticated user's password."""
    if not _check_password_change_rate_limit(user_id):
        raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")

    db_user = db.query(User).filter(User.id == int(user_id)).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(body.current_password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    if body.current_password == body.new_password:
        raise HTTPException(status_code=400, detail="New password must be different from current password")

    db_user.hashed_password = hash_password(body.new_password)
    db.commit()
    invalidate_user_cache(db_user.id)

    return {"message": "Password changed successfully"}


# ============================================================================
# GDPR COMPLIANCE ENDPOINTS (Phase 5)
# ============================================================================


@router.get("/api/user/export-data")
async def export_user_data(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """
    Export all user data in JSON format (GDPR Article 15 - Right of Access).

    Returns complete user data package including:
    - Profile information
    - Agents created
    - Documents uploaded
    - Conversations and messages
    - Team memberships
    """
    try:
        user = get_cached_user(user_id, db)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get all user agents
        agents = db.query(Agent).filter(Agent.user_id == int(user_id)).all()
        agents_data = []
        for agent in agents:
            # Get documents for this agent
            documents = db.query(Document).filter(Document.agent_id == agent.id).all()
            agents_data.append(
                {
                    "id": agent.id,
                    "name": agent.name,
                    "type": agent.type,
                    "statut": agent.statut,
                    "contexte": agent.contexte,
                    "biographie": agent.biographie,
                    "created_at": agent.created_at.isoformat() if agent.created_at else None,
                    "documents_count": len(documents),
                    "documents": [
                        {
                            "id": doc.id,
                            "filename": doc.filename,
                            "created_at": doc.created_at.isoformat() if doc.created_at else None,
                        }
                        for doc in documents
                    ],
                }
            )

        # Get all conversations
        conversations = db.query(Conversation).filter(Conversation.agent_id.in_([a.id for a in agents])).all()
        conversations_data = []
        for conv in conversations:
            messages = db.query(Message).filter(Message.conversation_id == conv.id).all()
            conversations_data.append(
                {
                    "id": conv.id,
                    "title": conv.title,
                    "agent_id": conv.agent_id,
                    "created_at": conv.created_at.isoformat() if conv.created_at else None,
                    "messages": [
                        {
                            "role": msg.role,
                            "content": msg.content,
                            "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
                            "feedback": msg.feedback,
                        }
                        for msg in messages
                    ],
                }
            )

        # Get team memberships
        teams = db.query(Team).filter(Team.user_id == int(user_id)).all()
        teams_data = [
            {
                "id": team.id,
                "name": team.name,
                "contexte": team.contexte,
                "created_at": team.created_at.isoformat() if team.created_at else None,
            }
            for team in teams
        ]

        export_data = {
            "export_date": datetime.utcnow().isoformat(),
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            },
            "agents": agents_data,
            "conversations": conversations_data,
            "teams": teams_data,
            "statistics": {
                "total_agents": len(agents),
                "total_documents": sum(len(a["documents"]) for a in agents_data),
                "total_conversations": len(conversations_data),
                "total_messages": sum(len(c["messages"]) for c in conversations_data),
                "total_teams": len(teams_data),
            },
        }

        logger.info(f"User {user_id} exported their data (GDPR Art. 15)")
        return export_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting user data: {e}")
        raise HTTPException(status_code=500, detail="Failed to export data")


@router.get("/api/user/stats")
async def get_user_stats(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Get analytics data for the current user's activity."""
    try:
        from sqlalchemy import func, cast, Date

        uid = int(user_id)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)

        # 1. Messages per day (last 30 days)
        messages_per_day_q = (
            db.query(cast(Message.timestamp, Date).label("date"), func.count(Message.id).label("count"))
            .join(Conversation, Message.conversation_id == Conversation.id)
            .filter(Conversation.user_id == uid)
            .filter(Message.timestamp >= thirty_days_ago)
            .group_by(cast(Message.timestamp, Date))
            .order_by(cast(Message.timestamp, Date))
            .all()
        )
        messages_per_day = [{"date": str(r.date), "count": r.count} for r in messages_per_day_q]

        # 2. Messages per agent
        messages_per_agent_q = (
            db.query(Agent.name.label("name"), func.count(Message.id).label("messages"))
            .join(Conversation, Message.conversation_id == Conversation.id)
            .join(Agent, Conversation.agent_id == Agent.id)
            .filter(Conversation.user_id == uid)
            .group_by(Agent.name)
            .order_by(func.count(Message.id).desc())
            .all()
        )
        messages_per_agent = [{"name": r.name, "messages": r.messages} for r in messages_per_agent_q]

        # 3. Conversations per agent
        conversations_per_agent_q = (
            db.query(Agent.name.label("name"), func.count(Conversation.id).label("conversations"))
            .join(Agent, Conversation.agent_id == Agent.id)
            .filter(Conversation.user_id == uid)
            .group_by(Agent.name)
            .order_by(func.count(Conversation.id).desc())
            .all()
        )
        conversations_per_agent = [
            {"name": r.name, "conversations": r.conversations} for r in conversations_per_agent_q
        ]

        # 4. Feedback distribution (agent messages only)
        feedback_q = (
            db.query(Message.feedback, func.count(Message.id).label("count"))
            .join(Conversation, Message.conversation_id == Conversation.id)
            .filter(Conversation.user_id == uid)
            .filter(Message.role == "agent")
            .group_by(Message.feedback)
            .all()
        )
        feedback = {"like": 0, "dislike": 0, "none": 0}
        for r in feedback_q:
            key = r.feedback if r.feedback in ("like", "dislike") else "none"
            feedback[key] += r.count

        # 5. Average messages per conversation
        subq = (
            db.query(Conversation.id, func.count(Message.id).label("msg_count"))
            .join(Message, Message.conversation_id == Conversation.id)
            .filter(Conversation.user_id == uid)
            .group_by(Conversation.id)
            .subquery()
        )
        avg_result = db.query(func.avg(subq.c.msg_count)).scalar()
        avg_messages = round(float(avg_result), 1) if avg_result else 0

        # 6. Role distribution (user vs agent messages)
        role_q = (
            db.query(Message.role, func.count(Message.id).label("count"))
            .join(Conversation, Message.conversation_id == Conversation.id)
            .filter(Conversation.user_id == uid)
            .group_by(Message.role)
            .all()
        )
        role_distribution = {"user": 0, "agent": 0}
        for r in role_q:
            if r.role in role_distribution:
                role_distribution[r.role] = r.count

        # Most active agent
        most_active_agent = messages_per_agent[0]["name"] if messages_per_agent else None

        return {
            "messages_per_day": messages_per_day,
            "messages_per_agent": messages_per_agent,
            "conversations_per_agent": conversations_per_agent,
            "feedback": feedback,
            "avg_messages_per_conversation": avg_messages,
            "role_distribution": role_distribution,
            "most_active_agent": most_active_agent,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch stats")


@router.delete("/api/user/delete-account")
async def delete_user_account(
    user_id: str = Depends(verify_token), db: Session = Depends(get_db), anonymize: bool = False
):
    """
    Delete user account and all associated data (GDPR Article 17 - Right to Erasure).

    Query params:
    - anonymize: If True, anonymize data instead of deleting (keeps analytics)

    Deletes/Anonymizes:
    - User profile
    - All agents created by user
    - All documents uploaded
    - All conversations and messages
    - All teams created by user
    """
    try:
        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if anonymize:
            # Anonymize instead of delete (GDPR-compliant)
            user.username = f"deleted_user_{user.id}"
            user.email = f"deleted_{user.id}@anonymized.local"
            user.hashed_password = "ANONYMIZED"

            # Anonymize agents
            agents = db.query(Agent).filter(Agent.user_id == int(user_id)).all()
            for agent in agents:
                agent.name = f"Anonymized Agent {agent.id}"
                agent.contexte = "ANONYMIZED"
                agent.biographie = "ANONYMIZED"

            db.commit()
            invalidate_user_cache(user.id)
            logger.info(f"User {user_id} account anonymized (GDPR Art. 17)")
            return {"message": "Account anonymized successfully", "anonymized": True, "user_id": user.id}
        else:
            # Complete deletion
            # Get all agents
            agents = db.query(Agent).filter(Agent.user_id == int(user_id)).all()
            agent_ids = [agent.id for agent in agents]

            # Delete conversations and messages for user's agents
            if agent_ids:
                conversations = db.query(Conversation).filter(Conversation.agent_id.in_(agent_ids)).all()
                conv_ids = [conv.id for conv in conversations]

                if conv_ids:
                    # Delete messages
                    db.query(Message).filter(Message.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
                    # Delete conversations
                    db.query(Conversation).filter(Conversation.id.in_(conv_ids)).delete(synchronize_session=False)

            # Delete documents (will cascade to chunks)
            db.query(Document).filter(Document.user_id == int(user_id)).delete(synchronize_session=False)

            # Delete agents
            db.query(Agent).filter(Agent.user_id == int(user_id)).delete(synchronize_session=False)

            # Delete teams
            db.query(Team).filter(Team.user_id == int(user_id)).delete(synchronize_session=False)

            # Delete password reset tokens
            db.query(PasswordResetToken).filter(PasswordResetToken.user_id == int(user_id)).delete(
                synchronize_session=False
            )

            # Finally delete user
            db.delete(user)
            db.commit()
            invalidate_user_cache(user_id)

            logger.info(f"User {user_id} account completely deleted (GDPR Art. 17)")
            return {"message": "Account deleted successfully", "anonymized": False, "deleted": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user account: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete account")
