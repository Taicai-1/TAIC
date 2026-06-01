"""Pydantic schemas for Companion Templates."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class TemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)
    icon: Optional[str] = Field(None, max_length=50)
    default_contexte: Optional[str] = None
    default_biographie: Optional[str] = None
    default_type: str = Field("conversationnel", pattern="^(conversationnel|recherche_live|visuel)$")
    document_ids: Optional[List[int]] = None


class TemplateUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)
    icon: Optional[str] = Field(None, max_length=50)
    default_contexte: Optional[str] = None
    default_biographie: Optional[str] = None
    default_type: Optional[str] = Field(None, pattern="^(conversationnel|recherche_live|visuel)$")
    document_ids: Optional[List[int]] = None


class TemplateDocumentItem(BaseModel):
    id: int
    filename: str


class TemplateResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    category: Optional[str]
    icon: Optional[str]
    default_contexte: Optional[str]
    default_biographie: Optional[str]
    default_type: str
    document_count: int
    created_at: datetime
    updated_at: Optional[datetime]


class TemplateDetailResponse(TemplateResponse):
    documents: List[TemplateDocumentItem]


class TemplateListResponse(BaseModel):
    templates: List[TemplateResponse]


class TemplateDocumentsRequest(BaseModel):
    document_ids: List[int] = Field(..., min_length=1)


class CreateAgentFromTemplateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    contexte: Optional[str] = None
    biographie: Optional[str] = None
    type: Optional[str] = Field(None, pattern="^(conversationnel|recherche_live|visuel)$")
