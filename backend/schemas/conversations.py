"""Conversation-related Pydantic schemas."""

from pydantic import BaseModel, root_validator
from typing import Optional


class ConversationCreate(BaseModel):
    agent_id: Optional[int] = None
    team_id: Optional[int] = None
    title: Optional[str] = None

    @classmethod
    def validate_one_id(cls, values):
        if not values.get("agent_id") and not values.get("team_id"):
            raise ValueError("agent_id ou team_id doit être fourni")
        return values

    @root_validator(pre=True)
    def check_ids(cls, values):
        return cls.validate_one_id(values)


class MessageCreate(BaseModel):
    conversation_id: int
    role: str
    content: str


class MessageFeedbackRequest(BaseModel):
    feedback: str  # 'like' ou 'dislike'
