# Companion Templates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Companion Templates system — reusable blueprints that admins create and members use as shortcuts to spin up pre-configured agents.

**Architecture:** New `AgentTemplate` and `AgentTemplateDocument` database models with a dedicated API router (`routers/templates.py`). Frontend gets a new `/templates` page (grid of cards) and the agent creation modal gains a 2-step flow (choose template or start from scratch). Templates are scoped to the organization (company_id).

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, Next.js 14 (Pages Router), React 18, Tailwind CSS, next-i18next, lucide-react.

**Spec:** `docs/superpowers/specs/2026-06-01-companion-templates-design.md`

---

## File Structure

### Files to Create

| File | Responsibility |
|------|---------------|
| `backend/routers/templates.py` | All template API endpoints (CRUD + create-agent) |
| `backend/schemas/templates.py` | Pydantic request/response models |
| `backend/tests/test_endpoints_templates.py` | Integration tests for template endpoints |
| `frontend/pages/templates.js` | Templates management page |
| `frontend/public/locales/fr/templates.json` | French translations |
| `frontend/public/locales/en/templates.json` | English translations |

### Files to Modify

| File | Change |
|------|--------|
| `backend/database.py` | Add `AgentTemplate`, `AgentTemplateDocument` models; add `template_id` to `Agent` |
| `backend/main.py` | Import + include templates router |
| `backend/tests/factories.py` | Add `AgentTemplateFactory`, `AgentTemplateDocumentFactory` |
| `backend/tests/conftest.py` | Add `test_company`, `test_admin_user`, `test_membership` fixtures |
| `frontend/components/Sidebar.js` | Add Templates nav item after Companions |
| `frontend/pages/agents.js` | 2-step creation modal with template picker |
| `frontend/next-i18next.config.js` | Add `'templates'` to `ns` array |
| `frontend/public/locales/fr/common.json` | Add `navigation.templates` key |
| `frontend/public/locales/en/common.json` | Add `navigation.templates` key |

---

### Task 1: Database Models

**Files:**
- Modify: `backend/database.py`
- Modify: `backend/tests/factories.py`

- [ ] **Step 1: Add AgentTemplate model to database.py**

Add after the `Agent` class (around line 326, before `AgentShare`):

```python
class AgentTemplate(Base):
    __tablename__ = "agent_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=True)
    icon = Column(String(50), nullable=True)
    default_contexte = Column(Text, nullable=True)
    default_biographie = Column(Text, nullable=True)
    default_type = Column(String(32), nullable=False, default="conversationnel")
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)

    company = relationship("Company")
    creator = relationship("User")
    template_documents = relationship("AgentTemplateDocument", back_populates="template", cascade="all, delete-orphan")


class AgentTemplateDocument(Base):
    __tablename__ = "agent_template_documents"
    __table_args__ = (UniqueConstraint("template_id", "document_id", name="uq_template_document"),)

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("agent_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)

    template = relationship("AgentTemplate", back_populates="template_documents")
    document = relationship("Document")
```

Also add `UniqueConstraint` to the imports at the top of `database.py` if not already present.

- [ ] **Step 2: Add template_id to Agent model**

In the `Agent` class, add after the `neo4j_depth` field (around line 314):

```python
    template_id = Column(Integer, ForeignKey("agent_templates.id", ondelete="SET NULL"), nullable=True)
```

- [ ] **Step 3: Add factories**

In `backend/tests/factories.py`, add the imports and factories:

Add `AgentTemplate, AgentTemplateDocument` to the imports from `database`.

```python
class AgentTemplateFactory(factory.Factory):
    class Meta:
        model = AgentTemplate

    name = factory.Sequence(lambda n: f"template-{n}")
    description = "Test template description"
    category = "Tech"
    icon = "Monitor"
    default_contexte = "Tu es un expert technique."
    default_biographie = "Assistant technique"
    default_type = "conversationnel"


class AgentTemplateDocumentFactory(factory.Factory):
    class Meta:
        model = AgentTemplateDocument
```

- [ ] **Step 4: Add test fixtures for company + admin**

In `backend/tests/conftest.py`, add these fixtures:

```python
@pytest.fixture
def test_company(db_session):
    """Create a test company."""
    from tests.factories import CompanyFactory

    company = CompanyFactory.build()
    db_session.add(company)
    db_session.flush()
    return company


@pytest.fixture
def test_admin_user(db_session, test_company):
    """Create an admin user in the test company."""
    from tests.factories import UserFactory, CompanyMembershipFactory

    user = UserFactory.build(company_id=test_company.id)
    db_session.add(user)
    db_session.flush()

    membership = CompanyMembershipFactory.build(
        user_id=user.id, company_id=test_company.id, role="admin"
    )
    db_session.add(membership)
    db_session.flush()
    return user


@pytest.fixture
def test_admin_token(test_admin_user):
    """Return a valid JWT token for the admin user."""
    return create_access_token(data={"sub": str(test_admin_user.id)})


@pytest.fixture
def admin_cookies(test_admin_token):
    """Return cookies dict for authenticated admin requests."""
    return {"token": test_admin_token}


@pytest.fixture
def test_member_user(db_session, test_company):
    """Create a member user in the test company."""
    from tests.factories import UserFactory, CompanyMembershipFactory

    user = UserFactory.build(company_id=test_company.id)
    db_session.add(user)
    db_session.flush()

    membership = CompanyMembershipFactory.build(
        user_id=user.id, company_id=test_company.id, role="member"
    )
    db_session.add(membership)
    db_session.flush()
    return user


@pytest.fixture
def test_member_token(test_member_user):
    """Return a valid JWT token for the member user."""
    return create_access_token(data={"sub": str(test_member_user.id)})


@pytest.fixture
def member_cookies(test_member_token):
    """Return cookies dict for authenticated member requests."""
    return {"token": test_member_token}
```

- [ ] **Step 5: Run existing tests to verify nothing is broken**

Run: `cd backend && python -m pytest tests/ -x -q`
Expected: All existing tests pass (new models don't affect them).

- [ ] **Step 6: Commit**

```bash
git add backend/database.py backend/tests/factories.py backend/tests/conftest.py
git commit -m "feat(templates): add AgentTemplate and AgentTemplateDocument models"
```

---

### Task 2: Pydantic Schemas

**Files:**
- Create: `backend/schemas/templates.py`

- [ ] **Step 1: Create schemas file**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add backend/schemas/templates.py
git commit -m "feat(templates): add Pydantic request/response schemas"
```

---

### Task 3: Template API Router — CRUD Endpoints

**Files:**
- Create: `backend/routers/templates.py`
- Modify: `backend/main.py`
- Create: `backend/tests/test_endpoints_templates.py`

- [ ] **Step 1: Write the failing tests for template CRUD**

Create `backend/tests/test_endpoints_templates.py`:

```python
"""Integration tests for template CRUD endpoints."""

import pytest
from tests.factories import AgentTemplateFactory, DocumentFactory


@pytest.mark.asyncio
async def test_list_templates_empty(client, admin_cookies, test_company):
    """Org with no templates should return empty list."""
    resp = await client.get("/api/templates", cookies=admin_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert "templates" in data
    assert len(data["templates"]) == 0


@pytest.mark.asyncio
async def test_create_template(client, admin_cookies, test_company):
    """Admin can create a template."""
    body = {
        "name": "CTO Template",
        "description": "Expert technique",
        "category": "Tech",
        "icon": "Monitor",
        "default_contexte": "Tu es un CTO expert.",
        "default_biographie": "CTO assistant",
        "default_type": "conversationnel",
    }
    resp = await client.post("/api/templates", json=body, cookies=admin_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert data["template"]["name"] == "CTO Template"
    assert data["template"]["category"] == "Tech"
    assert data["template"]["document_count"] == 0


@pytest.mark.asyncio
async def test_create_template_member_forbidden(client, member_cookies, test_company):
    """Member cannot create a template."""
    body = {"name": "Forbidden Template"}
    resp = await client.post("/api/templates", json=body, cookies=member_cookies)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_template_detail(client, db_session, admin_cookies, test_company, test_admin_user):
    """GET template detail returns documents."""
    template = AgentTemplateFactory.build(
        company_id=test_company.id, created_by_user_id=test_admin_user.id
    )
    db_session.add(template)
    db_session.flush()

    resp = await client.get(f"/api/templates/{template.id}", cookies=admin_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert data["template"]["name"] == template.name
    assert "documents" in data["template"]


@pytest.mark.asyncio
async def test_update_template(client, db_session, admin_cookies, test_company, test_admin_user):
    """Admin can update a template."""
    template = AgentTemplateFactory.build(
        company_id=test_company.id, created_by_user_id=test_admin_user.id
    )
    db_session.add(template)
    db_session.flush()

    resp = await client.put(
        f"/api/templates/{template.id}",
        json={"name": "Updated Name", "category": "RH"},
        cookies=admin_cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["template"]["name"] == "Updated Name"
    assert resp.json()["template"]["category"] == "RH"


@pytest.mark.asyncio
async def test_delete_template(client, db_session, admin_cookies, test_company, test_admin_user):
    """Admin can delete a template."""
    template = AgentTemplateFactory.build(
        company_id=test_company.id, created_by_user_id=test_admin_user.id
    )
    db_session.add(template)
    db_session.flush()
    tid = template.id

    resp = await client.delete(f"/api/templates/{tid}", cookies=admin_cookies)
    assert resp.status_code == 200

    # Verify it's gone
    resp2 = await client.get(f"/api/templates/{tid}", cookies=admin_cookies)
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_member_can_list_templates(client, db_session, member_cookies, test_company, test_admin_user):
    """Member can list org templates."""
    template = AgentTemplateFactory.build(
        company_id=test_company.id, created_by_user_id=test_admin_user.id
    )
    db_session.add(template)
    db_session.flush()

    resp = await client.get("/api/templates", cookies=member_cookies)
    assert resp.status_code == 200
    assert len(resp.json()["templates"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_endpoints_templates.py -x -q`
Expected: FAIL (router does not exist yet).

- [ ] **Step 3: Create the router**

Create `backend/routers/templates.py`:

```python
"""Companion Template CRUD and agent-creation endpoints."""

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
    TemplateDetailResponse,
    TemplateDocumentItem,
    TemplateDocumentsRequest,
    TemplateListResponse,
    TemplateResponse,
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


# --- CRUD ---


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
        company_id=company_id,
        created_by_user_id=user_id,
    )
    db.add(template)
    db.flush()

    # Link documents if provided
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

    for field, value in update_data.items():
        setattr(template, field, value)
    template.updated_at = datetime.utcnow()

    if document_ids is not None:
        # Replace all document associations
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


# --- Document management ---


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


# --- Create agent from template ---


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
    )
    db.add(agent)
    db.flush()

    # Copy template documents to the new agent
    for td in template.template_documents:
        src_doc = td.document
        if src_doc is None:
            logger.warning("Template doc %d missing, skipping", td.document_id)
            continue

        # Create a document copy pointing to the new agent
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

        # Copy chunks with embeddings
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

    # Generate embedding for agent contexte
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


# --- Helpers ---


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
```

- [ ] **Step 4: Register the router in main.py**

In `backend/main.py`, add after line 497 (`from routers.recaps import ...`):

```python
from routers.templates import router as templates_router  # noqa: E402
```

And after line 513 (`app.include_router(recaps_router)`):

```python
app.include_router(templates_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_endpoints_templates.py -x -v`
Expected: All 8 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/templates.py backend/schemas/templates.py backend/main.py backend/tests/test_endpoints_templates.py
git commit -m "feat(templates): add template CRUD and create-agent API endpoints"
```

---

### Task 4: Frontend — i18n Setup

**Files:**
- Create: `frontend/public/locales/fr/templates.json`
- Create: `frontend/public/locales/en/templates.json`
- Modify: `frontend/public/locales/fr/common.json`
- Modify: `frontend/public/locales/en/common.json`
- Modify: `frontend/next-i18next.config.js`

- [ ] **Step 1: Create French translations**

Create `frontend/public/locales/fr/templates.json`:

```json
{
  "page": {
    "title": "Templates",
    "subtitle": "Modèles de companions réutilisables",
    "empty": "Aucun template pour le moment",
    "emptyDescription": "Créez des modèles de companions que votre équipe pourra utiliser."
  },
  "buttons": {
    "createNew": "Nouveau template",
    "createAgent": "Créer un companion",
    "edit": "Modifier",
    "delete": "Supprimer",
    "save": "Enregistrer",
    "cancel": "Annuler",
    "addDocuments": "Ajouter des documents",
    "removeDocument": "Retirer"
  },
  "form": {
    "name": { "label": "Nom du template", "placeholder": "Ex: CTO, Support Client..." },
    "description": { "label": "Description", "placeholder": "Décrivez l'utilité de ce template..." },
    "category": { "label": "Catégorie", "placeholder": "Ex: Tech, RH, Sales..." },
    "icon": { "label": "Icône", "placeholder": "Nom d'icône Lucide (ex: Monitor, Headset...)", "helpLink": "Voir les icônes disponibles" },
    "contexte": { "label": "Contexte (prompt système)", "placeholder": "Instructions pour l'IA..." },
    "biographie": { "label": "Biographie", "placeholder": "Description visible par les utilisateurs..." },
    "type": { "label": "Type de companion" },
    "documents": { "label": "Documents liés", "search": "Rechercher un document...", "noDocuments": "Aucun document disponible", "selected": "{{count}} document(s) sélectionné(s)" }
  },
  "modal": {
    "titleCreate": "Nouveau template",
    "titleEdit": "Modifier le template"
  },
  "toast": {
    "createSuccess": "Template créé avec succès",
    "updateSuccess": "Template mis à jour",
    "deleteSuccess": "Template supprimé",
    "createError": "Erreur lors de la création du template",
    "updateError": "Erreur lors de la mise à jour",
    "deleteError": "Erreur lors de la suppression"
  },
  "card": {
    "documents": "{{count}} doc(s)"
  },
  "filter": {
    "all": "Tous"
  },
  "confirm": {
    "deleteTitle": "Supprimer ce template ?",
    "deleteMessage": "Les companions créés depuis ce template ne seront pas affectés."
  },
  "agentCreation": {
    "stepTitle": "Créer un companion",
    "fromScratch": "Partir de zéro",
    "fromScratchDescription": "Configurez tout manuellement",
    "orFromTemplate": "ou depuis un template",
    "basedOn": "Basé sur le template",
    "noTemplates": "Aucun template disponible"
  }
}
```

- [ ] **Step 2: Create English translations**

Create `frontend/public/locales/en/templates.json`:

```json
{
  "page": {
    "title": "Templates",
    "subtitle": "Reusable companion blueprints",
    "empty": "No templates yet",
    "emptyDescription": "Create companion blueprints your team can use."
  },
  "buttons": {
    "createNew": "New template",
    "createAgent": "Create companion",
    "edit": "Edit",
    "delete": "Delete",
    "save": "Save",
    "cancel": "Cancel",
    "addDocuments": "Add documents",
    "removeDocument": "Remove"
  },
  "form": {
    "name": { "label": "Template name", "placeholder": "E.g. CTO, Customer Support..." },
    "description": { "label": "Description", "placeholder": "Describe what this template is for..." },
    "category": { "label": "Category", "placeholder": "E.g. Tech, HR, Sales..." },
    "icon": { "label": "Icon", "placeholder": "Lucide icon name (e.g. Monitor, Headset...)", "helpLink": "Browse available icons" },
    "contexte": { "label": "Context (system prompt)", "placeholder": "AI instructions..." },
    "biographie": { "label": "Biography", "placeholder": "User-facing description..." },
    "type": { "label": "Companion type" },
    "documents": { "label": "Linked documents", "search": "Search documents...", "noDocuments": "No documents available", "selected": "{{count}} document(s) selected" }
  },
  "modal": {
    "titleCreate": "New template",
    "titleEdit": "Edit template"
  },
  "toast": {
    "createSuccess": "Template created successfully",
    "updateSuccess": "Template updated",
    "deleteSuccess": "Template deleted",
    "createError": "Error creating template",
    "updateError": "Error updating template",
    "deleteError": "Error deleting template"
  },
  "card": {
    "documents": "{{count}} doc(s)"
  },
  "filter": {
    "all": "All"
  },
  "confirm": {
    "deleteTitle": "Delete this template?",
    "deleteMessage": "Companions created from this template will not be affected."
  },
  "agentCreation": {
    "stepTitle": "Create a companion",
    "fromScratch": "Start from scratch",
    "fromScratchDescription": "Configure everything manually",
    "orFromTemplate": "or from a template",
    "basedOn": "Based on template",
    "noTemplates": "No templates available"
  }
}
```

- [ ] **Step 3: Add navigation key to common.json (fr)**

In `frontend/public/locales/fr/common.json`, add in the `"navigation"` object:

```json
"templates": "Templates"
```

- [ ] **Step 4: Add navigation key to common.json (en)**

In `frontend/public/locales/en/common.json`, add in the `"navigation"` object:

```json
"templates": "Templates"
```

- [ ] **Step 5: Add namespace to next-i18next.config.js**

In `frontend/next-i18next.config.js`, change line 14:

```javascript
  ns: ['common', 'auth', 'agents', 'chat', 'teams', 'profile', 'dashboard', 'errors', 'organization', 'sources', 'templates'],
```

- [ ] **Step 6: Commit**

```bash
git add frontend/public/locales/ frontend/next-i18next.config.js
git commit -m "feat(templates): add i18n translations for templates feature"
```

---

### Task 5: Frontend — Sidebar Update

**Files:**
- Modify: `frontend/components/Sidebar.js`

- [ ] **Step 1: Add Templates nav item**

In `frontend/components/Sidebar.js`, add `LayoutTemplate` to the import from `lucide-react` (line 4):

```javascript
import { Bot, Users, Building2, Settings, LogOut, User, ChevronsLeft, ChevronsRight, LayoutTemplate } from 'lucide-react';
```

Then update `NAV_ITEMS` to add the Templates entry after agents (line 9):

```javascript
const NAV_ITEMS = [
  { href: '/agents',       labelKey: 'navigation.agents',       Icon: Bot },
  { href: '/templates',    labelKey: 'navigation.templates',    Icon: LayoutTemplate },
  { href: '/teams',        labelKey: 'navigation.teams',        Icon: Users },
  { href: '/organization', labelKey: 'navigation.organization', Icon: Building2 },
  { href: '/profile',      labelKey: 'navigation.profile',      Icon: Settings },
];
```

- [ ] **Step 2: Verify the dev server renders correctly**

Run: `cd frontend && npm run dev`
Open http://localhost:3000 — confirm "Templates" appears in the sidebar between Companions and Teams.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/Sidebar.js
git commit -m "feat(templates): add Templates nav item to sidebar"
```

---

### Task 6: Frontend — Templates Page

**Files:**
- Create: `frontend/pages/templates.js`

- [ ] **Step 1: Create the templates page**

Create `frontend/pages/templates.js`:

```javascript
import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/router";
import toast, { Toaster } from "react-hot-toast";
import { useTranslation } from "next-i18next";
import { serverSideTranslations } from "next-i18next/serverSideTranslations";
import {
  Plus,
  LayoutTemplate,
  X,
  Trash2,
  Pencil,
  FileText,
  Zap,
  Search,
} from "lucide-react";
import Layout from "../components/Layout";
import { useAuth } from "../hooks/useAuth";
import api from "../lib/api";

export default function TemplatesPage() {
  const { t } = useTranslation(["templates", "common", "errors", "agents"]);
  const { user, loading: authLoading, authenticated } = useAuth();
  const router = useRouter();

  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState(null);
  const [selectedCategory, setSelectedCategory] = useState(null);
  const [orgDocuments, setOrgDocuments] = useState([]);
  const [docSearch, setDocSearch] = useState("");
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    name: "",
    description: "",
    category: "",
    icon: "",
    default_contexte: "",
    default_biographie: "",
    default_type: "conversationnel",
    document_ids: [],
  });

  const isAdmin = user?.role === "admin" || user?.role === "owner";

  const loadTemplates = useCallback(async () => {
    try {
      const resp = await api.get("/api/templates");
      setTemplates(resp.data.templates || []);
    } catch (error) {
      if (error.response?.status === 401) router.push("/login");
    } finally {
      setLoading(false);
    }
  }, [router]);

  const loadOrgDocuments = useCallback(async () => {
    try {
      const resp = await api.get("/user/documents");
      setOrgDocuments(resp.data.documents || []);
    } catch {
      // silent
    }
  }, []);

  useEffect(() => {
    if (!authenticated) return;
    loadTemplates();
    loadOrgDocuments();
  }, [authenticated, loadTemplates, loadOrgDocuments]);

  const categories = [...new Set(templates.map((t) => t.category).filter(Boolean))];

  const filteredTemplates = selectedCategory
    ? templates.filter((t) => t.category === selectedCategory)
    : templates;

  const filteredDocs = orgDocuments.filter((d) =>
    d.filename.toLowerCase().includes(docSearch.toLowerCase())
  );

  const resetForm = () => {
    setForm({
      name: "",
      description: "",
      category: "",
      icon: "",
      default_contexte: "",
      default_biographie: "",
      default_type: "conversationnel",
      document_ids: [],
    });
    setEditingTemplate(null);
    setDocSearch("");
  };

  const openCreate = () => {
    resetForm();
    setShowForm(true);
  };

  const openEdit = async (template) => {
    try {
      const resp = await api.get(`/api/templates/${template.id}`);
      const tmpl = resp.data.template;
      setForm({
        name: tmpl.name || "",
        description: tmpl.description || "",
        category: tmpl.category || "",
        icon: tmpl.icon || "",
        default_contexte: tmpl.default_contexte || "",
        default_biographie: tmpl.default_biographie || "",
        default_type: tmpl.default_type || "conversationnel",
        document_ids: (tmpl.documents || []).map((d) => d.id),
      });
      setEditingTemplate(tmpl);
      setShowForm(true);
    } catch {
      toast.error(t("templates:toast.updateError"));
    }
  };

  const handleSave = async () => {
    if (!form.name.trim()) {
      toast.error(t("templates:form.name.placeholder"));
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name: form.name,
        description: form.description || null,
        category: form.category || null,
        icon: form.icon || null,
        default_contexte: form.default_contexte || null,
        default_biographie: form.default_biographie || null,
        default_type: form.default_type,
        document_ids: form.document_ids,
      };

      if (editingTemplate) {
        await api.put(`/api/templates/${editingTemplate.id}`, payload);
        toast.success(t("templates:toast.updateSuccess"));
      } else {
        await api.post("/api/templates", payload);
        toast.success(t("templates:toast.createSuccess"));
      }
      setShowForm(false);
      resetForm();
      loadTemplates();
    } catch {
      toast.error(
        editingTemplate
          ? t("templates:toast.updateError")
          : t("templates:toast.createError")
      );
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (templateId) => {
    if (!confirm(t("templates:confirm.deleteMessage"))) return;
    try {
      await api.delete(`/api/templates/${templateId}`);
      toast.success(t("templates:toast.deleteSuccess"));
      loadTemplates();
    } catch {
      toast.error(t("templates:toast.deleteError"));
    }
  };

  const handleUseTemplate = (templateId) => {
    router.push(`/agents?template_id=${templateId}`);
  };

  const toggleDocSelection = (docId) => {
    setForm((f) => ({
      ...f,
      document_ids: f.document_ids.includes(docId)
        ? f.document_ids.filter((id) => id !== docId)
        : [...f.document_ids, docId],
    }));
  };

  if (authLoading || loading) {
    return (
      <Layout>
        <div className="flex items-center justify-center min-h-[60vh]">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <Toaster position="top-right" />
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-heading font-extrabold text-slate-900">
              {t("templates:page.title")}
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              {t("templates:page.subtitle")}
            </p>
          </div>
          {isAdmin && (
            <button
              onClick={openCreate}
              className="flex items-center px-6 py-3 bg-primary-600 hover:bg-primary-700 text-white rounded-button font-semibold shadow-card hover:shadow-elevated transition-all"
            >
              <Plus className="w-5 h-5 mr-2" />
              {t("templates:buttons.createNew")}
            </button>
          )}
        </div>

        {/* Category filters */}
        {categories.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-6">
            <button
              onClick={() => setSelectedCategory(null)}
              className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
                !selectedCategory
                  ? "bg-primary-600 text-white"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {t("templates:filter.all")}
            </button>
            {categories.map((cat) => (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
                  selectedCategory === cat
                    ? "bg-primary-600 text-white"
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        )}

        {/* Template grid */}
        {filteredTemplates.length === 0 ? (
          <div className="text-center py-16">
            <LayoutTemplate className="w-16 h-16 text-gray-300 mx-auto mb-4" />
            <h3 className="text-lg font-semibold text-gray-600">
              {t("templates:page.empty")}
            </h3>
            <p className="text-sm text-gray-400 mt-1">
              {t("templates:page.emptyDescription")}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredTemplates.map((template) => (
              <div
                key={template.id}
                className="bg-white border border-gray-200 rounded-card shadow-card hover:shadow-elevated transition-all p-6 flex flex-col"
              >
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-10 h-10 bg-primary-50 rounded-lg flex items-center justify-center">
                    <LayoutTemplate className="w-5 h-5 text-primary-600" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-gray-900 truncate">
                      {template.name}
                    </h3>
                    {template.category && (
                      <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
                        {template.category}
                      </span>
                    )}
                  </div>
                </div>

                {template.description && (
                  <p className="text-sm text-gray-500 mb-3 line-clamp-2">
                    {template.description}
                  </p>
                )}

                <div className="mt-auto flex items-center justify-between pt-3 border-t border-gray-100">
                  <span className="text-xs text-gray-400">
                    {t("templates:card.documents", {
                      count: template.document_count,
                    })}
                  </span>
                  <div className="flex gap-2">
                    {isAdmin && (
                      <>
                        <button
                          onClick={() => openEdit(template)}
                          className="p-1.5 text-gray-400 hover:text-primary-600 hover:bg-primary-50 rounded-md transition-colors"
                          title={t("templates:buttons.edit")}
                        >
                          <Pencil className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleDelete(template.id)}
                          className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-md transition-colors"
                          title={t("templates:buttons.delete")}
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </>
                    )}
                    <button
                      onClick={() => handleUseTemplate(template.id)}
                      className="px-3 py-1.5 bg-primary-600 hover:bg-primary-700 text-white text-xs font-medium rounded-button transition-colors"
                    >
                      {t("templates:buttons.createAgent")}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Create/Edit Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-[100] p-4">
          <div className="bg-white rounded-card shadow-floating p-8 w-full max-w-lg mx-auto max-h-[85vh] overflow-auto border border-gray-200 animate-fade-in">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-heading font-bold text-gray-900">
                {editingTemplate
                  ? t("templates:modal.titleEdit")
                  : t("templates:modal.titleCreate")}
              </h2>
              <button
                onClick={() => {
                  setShowForm(false);
                  resetForm();
                }}
                className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-md transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="space-y-4">
              {/* Name */}
              <div>
                <label className="text-sm font-medium text-gray-700 mb-1 block">
                  {t("templates:form.name.label")}
                </label>
                <input
                  type="text"
                  className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white"
                  placeholder={t("templates:form.name.placeholder")}
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                />
              </div>

              {/* Description */}
              <div>
                <label className="text-sm font-medium text-gray-700 mb-1 block">
                  {t("templates:form.description.label")}
                </label>
                <textarea
                  className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white resize-none"
                  placeholder={t("templates:form.description.placeholder")}
                  rows="2"
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                />
              </div>

              {/* Category + Icon */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-sm font-medium text-gray-700 mb-1 block">
                    {t("templates:form.category.label")}
                  </label>
                  <input
                    type="text"
                    className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white"
                    placeholder={t("templates:form.category.placeholder")}
                    value={form.category}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, category: e.target.value }))
                    }
                  />
                </div>
                <div>
                  <label className="text-sm font-medium text-gray-700 mb-1 block">
                    {t("templates:form.icon.label")}
                  </label>
                  <input
                    type="text"
                    className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white"
                    placeholder={t("templates:form.icon.placeholder")}
                    value={form.icon}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, icon: e.target.value }))
                    }
                  />
                </div>
              </div>

              {/* Contexte */}
              <div>
                <label className="text-sm font-medium text-gray-700 mb-1 block">
                  {t("templates:form.contexte.label")}
                </label>
                <textarea
                  className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white resize-none"
                  placeholder={t("templates:form.contexte.placeholder")}
                  rows="4"
                  value={form.default_contexte}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, default_contexte: e.target.value }))
                  }
                />
              </div>

              {/* Biographie */}
              <div>
                <label className="text-sm font-medium text-gray-700 mb-1 block">
                  {t("templates:form.biographie.label")}
                </label>
                <textarea
                  className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white resize-none"
                  placeholder={t("templates:form.biographie.placeholder")}
                  rows="2"
                  value={form.default_biographie}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      default_biographie: e.target.value,
                    }))
                  }
                />
              </div>

              {/* Type */}
              <div>
                <label className="text-sm font-medium text-gray-700 mb-1 block flex items-center">
                  <Zap className="w-4 h-4 mr-2 text-purple-600" />
                  {t("templates:form.type.label")}
                </label>
                <select
                  className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white font-medium"
                  value={form.default_type}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, default_type: e.target.value }))
                  }
                >
                  <option value="conversationnel">
                    {t("agents:types.conversationnel.name")} -{" "}
                    {t("agents:types.conversationnel.description")}
                  </option>
                  <option value="recherche_live">
                    {t("agents:types.recherche_live.name")} -{" "}
                    {t("agents:types.recherche_live.description")}
                  </option>
                  <option value="visuel">
                    {t("agents:types.visuel.name")} -{" "}
                    {t("agents:types.visuel.description")}
                  </option>
                </select>
              </div>

              {/* Document picker */}
              <div>
                <label className="text-sm font-medium text-gray-700 mb-1 block flex items-center">
                  <FileText className="w-4 h-4 mr-2 text-primary-600" />
                  {t("templates:form.documents.label")}
                </label>
                {form.document_ids.length > 0 && (
                  <p className="text-xs text-primary-600 mb-2">
                    {t("templates:form.documents.selected", {
                      count: form.document_ids.length,
                    })}
                  </p>
                )}
                <div className="relative mb-2">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type="text"
                    className="w-full pl-9 pr-4 py-2 border border-gray-200 rounded-input focus:border-primary-500 focus:ring-2 focus:ring-primary-100 transition-all outline-none bg-white text-sm"
                    placeholder={t("templates:form.documents.search")}
                    value={docSearch}
                    onChange={(e) => setDocSearch(e.target.value)}
                  />
                </div>
                <div className="max-h-40 overflow-auto border border-gray-200 rounded-input">
                  {filteredDocs.length === 0 ? (
                    <p className="text-xs text-gray-400 p-3 text-center">
                      {t("templates:form.documents.noDocuments")}
                    </p>
                  ) : (
                    filteredDocs.map((doc) => (
                      <label
                        key={doc.id}
                        className="flex items-center gap-3 px-3 py-2 hover:bg-gray-50 cursor-pointer border-b border-gray-100 last:border-0"
                      >
                        <input
                          type="checkbox"
                          checked={form.document_ids.includes(doc.id)}
                          onChange={() => toggleDocSelection(doc.id)}
                          className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                        />
                        <span className="text-sm text-gray-700 truncate">
                          {doc.filename}
                        </span>
                      </label>
                    ))
                  )}
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="flex space-x-4 mt-8">
              <button
                onClick={() => {
                  setShowForm(false);
                  resetForm();
                }}
                className="flex-1 px-6 py-3 text-gray-700 bg-white border border-gray-200 rounded-button hover:bg-gray-50 hover:border-gray-300 transition-all font-medium"
              >
                {t("templates:buttons.cancel")}
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex-1 px-6 py-3 bg-primary-600 hover:bg-primary-700 text-white rounded-button transition-all font-semibold shadow-card hover:shadow-elevated disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {saving ? (
                  <div className="flex items-center justify-center">
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></div>
                    {t("common:states.saving")}
                  </div>
                ) : (
                  t("templates:buttons.save")
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}

export async function getServerSideProps({ locale }) {
  return {
    props: {
      ...(await serverSideTranslations(locale, [
        "templates",
        "common",
        "errors",
        "agents",
      ])),
    },
  };
}
```

- [ ] **Step 2: Verify the page renders**

Run: `cd frontend && npm run dev`
Open http://localhost:3000/templates — confirm the page loads with empty state. If admin, confirm the "+ Nouveau template" button appears and the modal opens.

- [ ] **Step 3: Commit**

```bash
git add frontend/pages/templates.js
git commit -m "feat(templates): add /templates page with grid, CRUD modal, and document picker"
```

---

### Task 7: Frontend — 2-Step Agent Creation Modal

**Files:**
- Modify: `frontend/pages/agents.js`

- [ ] **Step 1: Add template state and fetch logic**

At the top of `AgentsPage` (after existing state declarations around line 43), add:

```javascript
  const [templates, setTemplates] = useState([]);
  const [creationStep, setCreationStep] = useState(1); // 1 = choose, 2 = form
  const [selectedTemplate, setSelectedTemplate] = useState(null);
```

Add a `loadTemplates` function after `loadNeo4jData`:

```javascript
  const loadTemplates = async () => {
    try {
      const resp = await api.get('/api/templates');
      setTemplates(resp.data.templates || []);
    } catch {
      // Templates are optional, silent fail
    }
  };
```

In the `useEffect` that calls `loadAgents()` and `loadNeo4jData()` (around line 46), add `loadTemplates()`:

```javascript
  useEffect(() => {
    if (!authenticated) return;
    loadAgents();
    loadNeo4jData();
    loadTemplates();
  }, [authenticated]);
```

- [ ] **Step 2: Add query param support for template_id**

After the existing useEffect blocks, add:

```javascript
  useEffect(() => {
    const templateId = router.query.template_id;
    if (templateId && templates.length > 0) {
      const tmpl = templates.find(t => t.id === parseInt(templateId));
      if (tmpl) {
        handleSelectTemplate(tmpl);
      }
      // Clean up URL
      router.replace('/agents', undefined, { shallow: true });
    }
  }, [router.query.template_id, templates]);
```

- [ ] **Step 3: Add template selection handler**

Add after the `loadTemplates` function:

```javascript
  const handleSelectTemplate = async (template) => {
    try {
      const resp = await api.get(`/api/templates/${template.id}`);
      const tmpl = resp.data.template;
      setForm(f => ({
        ...f,
        name: "",
        contexte: tmpl.default_contexte || "",
        biographie: tmpl.default_biographie || "",
        type: tmpl.default_type || "conversationnel",
      }));
      setSelectedTemplate(tmpl);
      setCreationStep(2);
      setShowForm(true);
    } catch {
      toast.error(t('errors:generic'));
    }
  };
```

- [ ] **Step 4: Modify the "+ Nouveau companion" button onClick**

Replace the onClick handler of the create button (around line 206-210) to reset to step 1:

```javascript
            onClick={() => {
              setForm({ name: "", contexte: "", biographie: "", profile_photo: null, email: "", password: "", type: 'conversationnel', email_tags: [], neo4j_enabled: false, neo4j_person_name: "", neo4j_depth: 1, weekly_recap_enabled: false, weekly_recap_prompt: "", weekly_recap_recipients: [], recap_frequency: "weekly", recap_hour: 9 });
              setPhotoPreview(null);
              setSelectedTemplate(null);
              setCreationStep(templates.length > 0 ? 1 : 2);
              setShowForm(true);
            }}
```

- [ ] **Step 5: Add Step 1 UI inside the modal**

Inside the existing modal `{showForm && (...)}` block (around line 218), wrap the existing form content. Replace the modal inner content with a conditional:

After the modal title `<h2>` and before `<div className="space-y-4">`, add the step 1 conditional:

```javascript
              {creationStep === 1 ? (
                /* Step 1: Choose template or start from scratch */
                <div className="space-y-4">
                  {/* From scratch option */}
                  <button
                    onClick={() => {
                      setSelectedTemplate(null);
                      setCreationStep(2);
                    }}
                    className="w-full flex items-center gap-3 p-4 border-2 border-gray-200 rounded-button hover:border-primary-500 hover:bg-primary-50 transition-all text-left"
                  >
                    <div className="w-10 h-10 bg-gray-100 rounded-lg flex items-center justify-center">
                      <Plus className="w-5 h-5 text-gray-500" />
                    </div>
                    <div>
                      <div className="font-semibold text-gray-900 text-sm">{t('templates:agentCreation.fromScratch')}</div>
                      <div className="text-xs text-gray-500">{t('templates:agentCreation.fromScratchDescription')}</div>
                    </div>
                  </button>

                  {/* Separator */}
                  <div className="flex items-center gap-3">
                    <div className="flex-1 h-px bg-gray-200"></div>
                    <span className="text-xs text-gray-400">{t('templates:agentCreation.orFromTemplate')}</span>
                    <div className="flex-1 h-px bg-gray-200"></div>
                  </div>

                  {/* Template grid */}
                  <div className="grid grid-cols-2 gap-3">
                    {templates.map((tmpl) => (
                      <button
                        key={tmpl.id}
                        onClick={() => handleSelectTemplate(tmpl)}
                        className="flex flex-col items-start p-3 border-2 border-gray-200 rounded-button hover:border-primary-500 hover:bg-primary-50 transition-all text-left"
                      >
                        <div className="w-8 h-8 bg-primary-50 rounded-lg flex items-center justify-center mb-2">
                          <Bot className="w-4 h-4 text-primary-600" />
                        </div>
                        <div className="font-semibold text-sm text-gray-900">{tmpl.name}</div>
                        <div className="text-xs text-gray-400">{t('templates:card.documents', { count: tmpl.document_count })}</div>
                      </button>
                    ))}
                  </div>

                  {/* Cancel */}
                  <button
                    onClick={() => { setShowForm(false); }}
                    className="w-full px-6 py-3 text-gray-700 bg-white border border-gray-200 rounded-button hover:bg-gray-50 transition-all font-medium mt-4"
                  >
                    {t('agents:buttons.cancel')}
                  </button>
                </div>
              ) : (
                /* Step 2: existing form - keep all the existing form JSX here */
                <>
                  {selectedTemplate && (
                    <div className="mb-4 px-3 py-2 bg-primary-50 border border-primary-200 rounded-button text-sm text-primary-700 flex items-center gap-2">
                      <Bot className="w-4 h-4" />
                      {t('templates:agentCreation.basedOn')} <strong>{selectedTemplate.name}</strong>
                    </div>
                  )}
                  {/* ... existing <div className="space-y-4"> with all form fields ... */}
```

Close the ternary after the existing form's closing `</div>` for the buttons:

```javascript
                </>
              )}
```

- [ ] **Step 6: Modify the submit handler for template-based creation**

In the submit button's `onClick` handler (around line 487-530), modify the API call to use the template endpoint when applicable:

Replace the existing `await api.post('/agents', formData, ...)` section with:

```javascript
                    if (selectedTemplate) {
                      // Create from template
                      await api.post(`/api/templates/${selectedTemplate.id}/create-agent`, {
                        name: form.name,
                        contexte: form.contexte || undefined,
                        biographie: form.biographie || undefined,
                        type: form.type || undefined,
                      });
                    } else {
                      // Create from scratch (existing logic)
                      await api.post('/agents', formData, {
                        headers: {
                          "Content-Type": "multipart/form-data"
                        }
                      });
                    }
```

- [ ] **Step 7: Verify the complete flow**

Run: `cd frontend && npm run dev`

1. Open http://localhost:3000/agents
2. Click "+ Nouveau companion" — should see step 1 with templates and "Partir de zero"
3. Click a template — form should open pre-filled
4. Click "Partir de zero" — form should open empty
5. Open http://localhost:3000/agents?template_id=1 — should auto-open with template pre-filled

- [ ] **Step 8: Commit**

```bash
git add frontend/pages/agents.js
git commit -m "feat(templates): add 2-step agent creation flow with template picker"
```

---

### Task 8: Frontend Lint + Final Verification

**Files:** None (verification only)

- [ ] **Step 1: Run frontend lint**

Run: `cd frontend && npm run lint`
Expected: No errors. Fix any warnings from new code.

- [ ] **Step 2: Run backend tests**

Run: `cd backend && python -m pytest tests/ -x -q`
Expected: All tests pass including the new template tests.

- [ ] **Step 3: Commit any lint fixes**

```bash
git add -A
git commit -m "chore: fix lint issues in templates feature"
```

(Skip this commit if no lint fixes were needed.)
