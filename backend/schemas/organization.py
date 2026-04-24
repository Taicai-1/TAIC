"""Organization-related Pydantic schemas."""

import re

from pydantic import BaseModel, validator
from typing import Optional


class SlashCommandItem(BaseModel):
    """Slash command with validation"""

    id: Optional[str] = None
    command: str
    prompt: str
    agent_ids: list[int] = []

    @validator("command")
    def validate_command(cls, v):
        if not v:
            raise ValueError("Command cannot be empty")
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("Command can only contain letters, numbers, dash, and underscore")
        if len(v) > 32:
            raise ValueError("Command must be 32 characters or less")
        return v.lower()

    @validator("prompt")
    def validate_prompt(cls, v):
        if not v or not v.strip():
            raise ValueError("Prompt cannot be empty")
        if len(v) > 5000:
            raise ValueError("Prompt must be 5000 characters or less")
        return v.strip()
