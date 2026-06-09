"""Pydantic schemas for questionnaire endpoints."""

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


# --- Question CRUD ---

class QuestionCreate(BaseModel):
    question_text: str = Field(..., min_length=1, max_length=2000)
    question_type: str = Field("open", pattern="^(open|single_choice|multiple_choice|rating)$")
    options: Optional[str] = None  # JSON string
    position: int = 0
    required: bool = True


class QuestionUpdate(BaseModel):
    question_text: Optional[str] = Field(None, min_length=1, max_length=2000)
    question_type: Optional[str] = Field(None, pattern="^(open|single_choice|multiple_choice|rating)$")
    options: Optional[str] = None
    position: Optional[int] = None
    required: Optional[bool] = None


class QuestionOut(BaseModel):
    id: int
    question_text: str
    question_type: str
    options: Optional[str] = None
    position: int
    required: bool

    class Config:
        from_attributes = True


class ReorderRequest(BaseModel):
    question_ids: List[int]


# --- Invitations ---

class InviteRequest(BaseModel):
    emails: List[str] = Field(..., min_length=1)
    names: Optional[List[str]] = None  # Parallel list of names (same order as emails)


# --- Responses ---

class ResponseSummary(BaseModel):
    id: int
    respondent_email: str
    respondent_name: Optional[str] = None
    status: str
    invited_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AnswerOut(BaseModel):
    id: int
    question_id: int
    question_text: str
    question_type: str
    answer_text: Optional[str] = None
    answered_at: Optional[datetime] = None


class ResponseDetail(BaseModel):
    id: int
    respondent_email: str
    respondent_name: Optional[str] = None
    status: str
    invited_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    answers: List[AnswerOut]


# --- Export ---

class ExportRequest(BaseModel):
    response_ids: List[int] = Field(..., min_length=1)
    target_agent_id: int


# --- Public questionnaire ---

class PublicQuestionnaireOut(BaseModel):
    agent_name: str
    welcome_message: Optional[str] = None
    questions: List[QuestionOut]


class PublicAnswerSubmit(BaseModel):
    question_id: int
    answer_text: str = Field(..., max_length=10000)
