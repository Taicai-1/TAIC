"""Pydantic schemas for the automations questionnaire feature."""

import re
from typing import List, Optional, Union

from pydantic import BaseModel, Field, field_validator

QUESTION_TYPE_PATTERN = "^(open|single_choice|multiple_choice|rating)$"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --- Questionnaire CRUD ---


class QuestionInput(BaseModel):
    question_text: str = Field(..., min_length=1, max_length=2000)
    question_type: str = Field("open", pattern=QUESTION_TYPE_PATTERN)
    # list of choices for single/multiple_choice, {"min","max"} for rating, None for open
    options: Optional[Union[List[str], dict]] = None
    position: int = 0
    required: bool = True

    @field_validator("question_text")
    @classmethod
    def validate_question_text(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("question_text cannot be blank")
        return v

    @field_validator("options")
    @classmethod
    def validate_options(cls, v, info):
        # NOTE: 'question_type' must be declared before 'options' in this model
        # so that info.data contains a validated question_type when this runs.
        # If question_type failed validation, info.data.get returns 'open' and
        # this validator acts as a no-op (the type error is already reported).
        qtype = info.data.get("question_type", "open")
        if qtype in ("single_choice", "multiple_choice"):
            if (
                not isinstance(v, list)
                or not v
                or not all(isinstance(o, str) and o.strip() for o in v)
            ):
                raise ValueError("choice questions need a non-empty list of option strings")
            return [o.strip() for o in v]
        if qtype == "rating":
            if not isinstance(v, dict):
                return {"min": 1, "max": 5}
            try:
                bounds = {"min": int(v.get("min", 1)), "max": int(v.get("max", 5))}
            except (TypeError, ValueError):
                raise ValueError("rating bounds must be integers")
            if bounds["min"] < 0:
                raise ValueError("rating min cannot be negative")
            if bounds["min"] >= bounds["max"]:
                raise ValueError("rating min must be lower than max")
            return bounds
        return None  # open questions carry no options


class QuestionnaireCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    questions: List[QuestionInput] = Field(default_factory=list, max_length=100)


class QuestionnaireUpdate(QuestionnaireCreate):
    pass


# --- Invitations ---


class InviteRecipient(BaseModel):
    email: str = Field(..., max_length=255)
    name: Optional[str] = Field(None, max_length=255)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError(f"invalid email address: {v}")
        return v


class InviteRequest(BaseModel):
    recipients: List[InviteRecipient] = Field(..., min_length=1, max_length=200)


# --- Export ---


class ExportRequest(BaseModel):
    response_ids: List[int] = Field(..., min_length=1, max_length=500)
    target_agent_id: int


# --- Public submit ---


class PublicAnswerItem(BaseModel):
    question_id: int
    # str (open/single_choice), list[str] (multiple_choice), int (rating)
    value: Union[str, List[str], int, None] = None


class PublicSubmitRequest(BaseModel):
    respondent_name: Optional[str] = Field(None, max_length=255)
    answers: List[PublicAnswerItem] = Field(default_factory=list, max_length=200)
