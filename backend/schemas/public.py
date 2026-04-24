"""Public endpoint Pydantic schemas."""

from pydantic import BaseModel
from typing import List, Optional


class PublicChatRequest(BaseModel):
    message: str
    history: Optional[List[dict]] = None
