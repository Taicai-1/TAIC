"""Pydantic schemas for the missions automation feature."""

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class MissionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    objective: str = Field(..., min_length=1, max_length=10000)
    agent_id: Optional[int] = None

    recap_enabled: bool = True
    recap_weekday: int = Field(0, ge=0, le=6)
    recap_hour: int = Field(8, ge=0, le=23)

    @field_validator("name", "objective")
    @classmethod
    def not_blank(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class MissionUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    objective: str = Field(..., min_length=1, max_length=10000)
    agent_id: Optional[int] = None
    status: str = Field("active", pattern="^(active|archived)$")
    recap_enabled: bool = True
    recap_weekday: int = Field(0, ge=0, le=6)
    recap_hour: int = Field(8, ge=0, le=23)
    recap_prompt: Optional[str] = Field(None, max_length=10000)

    @field_validator("name", "objective")
    @classmethod
    def not_blank(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class ParsedEvent(BaseModel):
    """One event in the planning. `date` accepts ISO YYYY-MM-DD (str or date)."""

    date: date
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("title must not be blank")
        return v


class EventsBulk(BaseModel):
    events: List[ParsedEvent] = Field(default_factory=list, max_length=1000)
    replace_upload: bool = False


class EventCreate(BaseModel):
    date: date
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("title must not be blank")
        return v


class EventUpdate(EventCreate):
    pass


class RecapScheduleCreate(BaseModel):
    kind: str = Field(..., pattern="^(recurring|once)$")
    weekday: Optional[int] = Field(None, ge=0, le=6)
    run_date: Optional[date] = None
    hour: int = Field(..., ge=0, le=23)
    enabled: bool = True
    recap_prompt: Optional[str] = Field(None, max_length=10000)

    @model_validator(mode="after")
    def check_kind_fields(self):
        if self.kind == "recurring" and self.weekday is None:
            raise ValueError("weekday is required for a recurring schedule")
        if self.kind == "once" and self.run_date is None:
            raise ValueError("run_date is required for a one-shot schedule")
        return self


class RecapScheduleUpdate(RecapScheduleCreate):
    pass


class MissionChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    conversation_id: Optional[int] = None
