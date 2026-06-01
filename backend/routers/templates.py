"""Companion Template CRUD and agent-creation endpoints."""

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth import verify_token
from database import (
    Agent,
    AgentTemplate,
    AgentTemplateDocument,
    Document,
    DocumentChunk,
    get_db,
)
from helpers.agent_helpers import resolve_llm_provider, update_agent_embedding
from helpers.tenant import _get_caller_company_id
from permissions import require_role
from schemas.templates import (
    CreateAgentFromTemplateRequest,
    TemplateCreateRequest,
    TemplateDocumentsRequest,
    TemplateUpdateRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _template_to_response(template: AgentTemplate) -> dict:
    """Convert an AgentTemplate ORM object to a response dict."""
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "category": template.category,
        "icon": template.icon,
        "default_contexte": template.default_contexte,
        "default_biographie": template.default_biographie,
        "default_type": template.default_type,
        "document_count": len(template.template_documents),
        "created_at": template.created_at.isoformat() if template.created_at else None,
        "updated_at": template.updated_at.isoformat() if template.updated_at else None,
        "default_email_tags": json.loads(template.default_email_tags) if template.default_email_tags else None,
        "default_neo4j_enabled": template.default_neo4j_enabled,
        "default_neo4j_person_name": template.default_neo4j_person_name,
        "default_neo4j_depth": template.default_neo4j_depth,
        "default_weekly_recap_enabled": template.default_weekly_recap_enabled,
        "default_weekly_recap_prompt": template.default_weekly_recap_prompt,
        "default_weekly_recap_recipients": json.loads(template.default_weekly_recap_recipients) if template.default_weekly_recap_recipients else None,
        "default_recap_frequency": template.default_recap_frequency,
        "default_recap_hour": template.default_recap_hour,
    }


def _template_to_detail(template: AgentTemplate) -> dict:
    """Convert to detail response including documents."""
    base = _template_to_response(template)
    base["documents"] = [
        {"id": td.document.id, "filename": td.document.filename}
        for td in template.template_documents
        if td.document is not None
    ]
    return base


def _get_template_or_404(template_id: int, company_id: int, db: Session) -> AgentTemplate:
    """Fetch a template by id scoped to company, or raise 404."""
    template = (
        db.query(AgentTemplate)
        .filter(AgentTemplate.id == template_id, AgentTemplate.company_id == company_id)
        .first()
    )
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.get("/api/templates")
async def list_templates(
    category: Optional[str] = Query(None),
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """List templates for the caller's organization."""
    membership = require_role(user_id, db, "member")
    company_id = membership.company_id

    query = db.query(AgentTemplate).filter(AgentTemplate.company_id == company_id)
    if category:
        query = query.filter(AgentTemplate.category == category)
    query = query.order_by(AgentTemplate.created_at.desc())

    templates = query.all()
    return {"templates": [_template_to_response(t) for t in templates]}


@router.post("/api/templates")
async def create_template(
    body: TemplateCreateRequest,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Create a new template. Admin only."""
    membership = require_role(user_id, db, "admin")
    company_id = membership.company_id

    template = AgentTemplate(
        name=body.name,
        description=body.description,
        category=body.category,
        icon=body.icon,
        default_contexte=body.default_contexte,
        default_biographie=body.default_biographie,
        default_type=body.default_type,
        default_email_tags=json.dumps(body.default_email_tags) if body.default_email_tags else None,
        default_neo4j_enabled=body.default_neo4j_enabled or False,
        default_neo4j_person_name=body.default_neo4j_person_name,
        default_neo4j_depth=body.default_neo4j_depth or 1,
        default_weekly_recap_enabled=body.default_weekly_recap_enabled or False,
        default_weekly_recap_prompt=body.default_weekly_recap_prompt,
        default_weekly_recap_recipients=json.dumps(body.default_weekly_recap_recipients) if body.default_weekly_recap_recipients else None,
        default_recap_frequency=body.default_recap_frequency or "weekly",
        default_recap_hour=body.default_recap_hour if body.default_recap_hour is not None else 9,
        company_id=company_id,
        created_by_user_id=user_id,
    )
    db.add(template)
    db.flush()

    if body.document_ids:
        _link_documents(template, body.document_ids, company_id, db)

    db.commit()
    db.refresh(template)
    return {"template": _template_to_response(template)}


@router.get("/api/templates/{template_id}")
async def get_template(
    template_id: int,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Get template detail with documents."""
    membership = require_role(user_id, db, "member")
    template = _get_template_or_404(template_id, membership.company_id, db)
    return {"template": _template_to_detail(template)}


@router.put("/api/templates/{template_id}")
async def update_template(
    template_id: int,
    body: TemplateUpdateRequest,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Update a template. Admin only."""
    membership = require_role(user_id, db, "admin")
    template = _get_template_or_404(template_id, membership.company_id, db)

    update_data = body.dict(exclude_unset=True)
    document_ids = update_data.pop("document_ids", None)

    # Remove list fields from update_data since we handle them separately with JSON encoding
    update_data.pop("default_email_tags", None)
    update_data.pop("default_weekly_recap_recipients", None)

    for field, value in update_data.items():
        setattr(template, field, value)
    template.updated_at = datetime.utcnow()

    if body.default_email_tags is not None:
        template.default_email_tags = json.dumps(body.default_email_tags) if body.default_email_tags else None
    if body.default_neo4j_enabled is not None:
        template.default_neo4j_enabled = body.default_neo4j_enabled
    if body.default_neo4j_person_name is not None:
        template.default_neo4j_person_name = body.default_neo4j_person_name
    if body.default_neo4j_depth is not None:
        template.default_neo4j_depth = body.default_neo4j_depth
    if body.default_weekly_recap_enabled is not None:
        template.default_weekly_recap_enabled = body.default_weekly_recap_enabled
    if body.default_weekly_recap_prompt is not None:
        template.default_weekly_recap_prompt = body.default_weekly_recap_prompt
    if body.default_weekly_recap_recipients is not None:
        template.default_weekly_recap_recipients = json.dumps(body.default_weekly_recap_recipients) if body.default_weekly_recap_recipients else None
    if body.default_recap_frequency is not None:
        template.default_recap_frequency = body.default_recap_frequency
    if body.default_recap_hour is not None:
        template.default_recap_hour = body.default_recap_hour

    if document_ids is not None:
        db.query(AgentTemplateDocument).filter(
            AgentTemplateDocument.template_id == template.id
        ).delete()
        _link_documents(template, document_ids, membership.company_id, db)

    db.commit()
    db.refresh(template)
    return {"template": _template_to_response(template)}


@router.delete("/api/templates/{template_id}")
async def delete_template(
    template_id: int,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Delete a template. Admin only."""
    membership = require_role(user_id, db, "admin")
    template = _get_template_or_404(template_id, membership.company_id, db)
    db.delete(template)
    db.commit()
    return {"success": True}


@router.post("/api/templates/{template_id}/documents")
async def add_template_documents(
    template_id: int,
    body: TemplateDocumentsRequest,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Link documents to a template. Admin only."""
    membership = require_role(user_id, db, "admin")
    template = _get_template_or_404(template_id, membership.company_id, db)
    _link_documents(template, body.document_ids, membership.company_id, db)
    db.commit()
    db.refresh(template)
    return {"template": _template_to_detail(template)}


@router.delete("/api/templates/{template_id}/documents/{document_id}")
async def remove_template_document(
    template_id: int,
    document_id: int,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Unlink a document from a template. Admin only."""
    membership = require_role(user_id, db, "admin")
    _get_template_or_404(template_id, membership.company_id, db)

    deleted = (
        db.query(AgentTemplateDocument)
        .filter(
            AgentTemplateDocument.template_id == template_id,
            AgentTemplateDocument.document_id == document_id,
        )
        .delete()
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not linked to this template")
    db.commit()
    return {"success": True}


@router.post("/api/templates/{template_id}/create-agent")
async def create_agent_from_template(
    template_id: int,
    body: CreateAgentFromTemplateRequest,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Create a new agent pre-filled from a template."""
    membership = require_role(user_id, db, "member")
    template = _get_template_or_404(template_id, membership.company_id, db)

    agent_type = body.type or template.default_type
    agent = Agent(
        name=body.name,
        contexte=body.contexte if body.contexte is not None else template.default_contexte,
        biographie=body.biographie if body.biographie is not None else template.default_biographie,
        type=agent_type,
        llm_provider=resolve_llm_provider(agent_type),
        template_id=template.id,
        company_id=membership.company_id,
        user_id=user_id,
        statut="privé",
        email_tags=json.dumps(body.email_tags) if body.email_tags is not None else template.default_email_tags,
        neo4j_enabled=body.neo4j_enabled if body.neo4j_enabled is not None else template.default_neo4j_enabled,
        neo4j_person_name=body.neo4j_person_name if body.neo4j_person_name is not None else template.default_neo4j_person_name,
        neo4j_depth=body.neo4j_depth if body.neo4j_depth is not None else template.default_neo4j_depth,
        weekly_recap_enabled=body.weekly_recap_enabled if body.weekly_recap_enabled is not None else template.default_weekly_recap_enabled,
        weekly_recap_prompt=body.weekly_recap_prompt if body.weekly_recap_prompt is not None else template.default_weekly_recap_prompt,
        weekly_recap_recipients=json.dumps(body.weekly_recap_recipients) if body.weekly_recap_recipients is not None else template.default_weekly_recap_recipients,
        recap_frequency=body.recap_frequency if body.recap_frequency is not None else template.default_recap_frequency,
        recap_hour=body.recap_hour if body.recap_hour is not None else template.default_recap_hour,
    )
    db.add(agent)
    db.flush()

    # Copy template documents to the new agent
    for td in template.template_documents:
        src_doc = td.document
        if src_doc is None:
            logger.warning("Template doc %d missing, skipping", td.document_id)
            continue

        new_doc = Document(
            filename=src_doc.filename,
            content=src_doc.content,
            gcs_url=src_doc.gcs_url,
            document_type=src_doc.document_type,
            source_url=src_doc.source_url,
            user_id=user_id,
            agent_id=agent.id,
            company_id=membership.company_id,
        )
        db.add(new_doc)
        db.flush()

        src_chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == src_doc.id)
            .order_by(DocumentChunk.chunk_index)
            .all()
        )
        for chunk in src_chunks:
            new_chunk = DocumentChunk(
                document_id=new_doc.id,
                company_id=membership.company_id,
                chunk_text=chunk.chunk_text,
                embedding=chunk.embedding,
                embedding_vec=chunk.embedding_vec,
                chunk_index=chunk.chunk_index,
            )
            db.add(new_chunk)

    if agent.contexte and agent.contexte.strip():
        try:
            update_agent_embedding(agent, db)
        except Exception:
            logger.warning("Failed to generate agent embedding, continuing")

    db.commit()
    db.refresh(agent)

    return {
        "agent": {
            "id": agent.id,
            "name": agent.name,
            "type": agent.type,
            "statut": agent.statut,
            "llm_provider": agent.llm_provider,
            "template_id": agent.template_id,
            "created_at": agent.created_at.isoformat() if agent.created_at else None,
        }
    }


def _link_documents(template: AgentTemplate, document_ids: list[int], company_id: int, db: Session):
    """Validate and link documents to a template."""
    existing_ids = {td.document_id for td in template.template_documents}

    for doc_id in document_ids:
        if doc_id in existing_ids:
            continue
        doc = db.query(Document).filter(Document.id == doc_id, Document.company_id == company_id).first()
        if not doc:
            raise HTTPException(status_code=400, detail=f"Document {doc_id} not found in your organization")
        link = AgentTemplateDocument(template_id=template.id, document_id=doc_id)
        db.add(link)
