"""Email ingestion Pydantic schemas."""

from pydantic import BaseModel
from typing import List, Optional


class EmailTag(BaseModel):
    name: str
    category: Optional[str] = None
    confidence: Optional[float] = None
    source: Optional[str] = None


class EmailMetadata(BaseModel):
    from_email: Optional[str] = None
    to: Optional[str] = None
    date: Optional[str] = None
    thread_id: Optional[str] = None
    has_attachments: Optional[bool] = False
    attachment_count: Optional[int] = 0
    priority: Optional[int] = None

    class Config:
        populate_by_name = True

    def __init__(self, **data):
        # Handle 'from' field mapping to 'from_email'
        if "from" in data:
            data["from_email"] = data.pop("from")
        super().__init__(**data)


class EmailIngestRequest(BaseModel):
    source: str
    source_id: str
    title: str
    content: str
    metadata: Optional[EmailMetadata] = None
    tags: Optional[List[EmailTag]] = None
    agent_id: Optional[int] = None  # Optionnel maintenant, on route par tags
