# Questionnaire Companion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `questionnaire` agent type that lets users build question sets, invite respondents via email, collect answers through a public conversational chat page, view responses, and export them into other agents' RAG pipelines.

**Architecture:** New SQLAlchemy models (`QuestionnaireQuestion`, `QuestionnaireResponse`, `QuestionnaireAnswer`) with tenant isolation. New backend router `routers/questionnaires.py` for CRUD + invite + export endpoints, plus public endpoints in `routers/public.py`. Frontend: question builder components in `components/questionnaire/`, new public page at `pages/questionnaire/[token].js`, modified agent creation form in `agents.js` to support the new type.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, Mistral API (welcome/closing messages), Brevo SMTP (invitations), weasyprint (PDF), Next.js/React/Tailwind (frontend)

---

## File Map

### Backend — New files
- `backend/schemas/questionnaires.py` — Pydantic request/response models
- `backend/routers/questionnaires.py` — All questionnaire CRUD, invite, response, export endpoints

### Backend — Modified files
- `backend/database.py` — Add 3 new SQLAlchemy models + update `ensure_columns` + update `ensure_rls_policies`
- `backend/validation.py:304` — Update `AgentCreateValidated.type` pattern to include `questionnaire`
- `backend/main.py:502-544` — Register the new questionnaires router
- `backend/routers/public.py` — Add 3 public questionnaire endpoints
- `backend/email_service.py` — Add `send_questionnaire_invitation_email` function

### Frontend — New files
- `frontend/components/questionnaire/QuestionBuilder.js` — Question builder for agent creation/edit
- `frontend/components/questionnaire/QuestionCard.js` — Single question card (type selector, options editor)
- `frontend/components/questionnaire/InvitationsTab.js` — Invitation management tab
- `frontend/components/questionnaire/ResponsesTab.js` — Response list + detail view
- `frontend/components/questionnaire/ExportModal.js` — Agent selector modal for RAG export
- `frontend/pages/questionnaire/[token].js` — Public conversational questionnaire page
- `frontend/public/locales/fr/questionnaire.json` — French translations
- `frontend/public/locales/en/questionnaire.json` — English translations

### Frontend — Modified files
- `frontend/pages/agents.js:31,261,370-376,636-655` — Add `questionnaire` type to form state, type selector, conditional rendering of question builder
- `frontend/pages/agents.js` (AgentCard section) — Show questionnaire-specific info on agent cards

---

## Task 1: Database models

**Files:**
- Modify: `backend/database.py:258-335` (after Agent class, before UserGoogleToken)
- Modify: `backend/database.py:807-868` (ensure_columns migrations list)
- Modify: `backend/database.py:928-941` (ensure_rls_policies tables list)

- [ ] **Step 1: Add the three new SQLAlchemy models to `database.py`**

Add these classes after the `Agent` class (after line 335) and before `UserGoogleToken`:

```python
class QuestionnaireQuestion(Base):
    __tablename__ = "questionnaire_questions"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    question_text = Column(Text, nullable=False)
    question_type = Column(String(20), nullable=False, default="open")  # open, single_choice, multiple_choice, rating
    options = Column(Text, nullable=True)  # JSON: ["Oui","Non"] or {"min":1,"max":5}
    position = Column(Integer, nullable=False, default=0)
    required = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent", foreign_keys=[agent_id])


class QuestionnaireResponse(Base):
    __tablename__ = "questionnaire_responses"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    respondent_email = Column(String(255), nullable=False)
    respondent_name = Column(String(255), nullable=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending")  # pending, in_progress, completed
    invited_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    agent = relationship("Agent", foreign_keys=[agent_id])
    answers = relationship("QuestionnaireAnswer", back_populates="response", cascade="all, delete-orphan")


class QuestionnaireAnswer(Base):
    __tablename__ = "questionnaire_answers"

    id = Column(Integer, primary_key=True, index=True)
    response_id = Column(Integer, ForeignKey("questionnaire_responses.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(Integer, ForeignKey("questionnaire_questions.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    answer_text = Column(Text, nullable=True)  # Free text or JSON for choices
    answered_at = Column(DateTime, default=datetime.utcnow)

    response = relationship("QuestionnaireResponse", back_populates="answers")
    question = relationship("QuestionnaireQuestion", foreign_keys=[question_id])
```

- [ ] **Step 2: Add `welcome_message` and `closing_message` columns to Agent model**

In the Agent class (around line 330, before the `# Relations` comment), add:

```python
    # Questionnaire-specific fields (only used when type='questionnaire')
    welcome_message = Column(Text, nullable=True)
    closing_message = Column(Text, nullable=True)
```

- [ ] **Step 3: Update `ensure_columns` migration list**

In the `ensure_columns()` function (around line 868, at the end of the migrations list), add:

```python
        # Questionnaire companion
        ("agents", "welcome_message", "TEXT"),
        ("agents", "closing_message", "TEXT"),
```

Note: The three new tables are created by `Base.metadata.create_all(engine)` at startup. `ensure_columns` only handles columns added to existing tables.

- [ ] **Step 4: Update `ensure_rls_policies` tables list**

In the `ensure_rls_policies()` function (around line 928-941), add the three new tables to the `tables` list:

```python
    tables = [
        "agents",
        "agent_shares",
        "documents",
        "document_chunks",
        "agent_actions",
        "teams",
        "conversations",
        "messages",
        "notion_links",
        "weekly_recap_logs",
        "recaps",
        "recap_documents",
        "questionnaire_questions",
        "questionnaire_responses",
        "questionnaire_answers",
    ]
```

- [ ] **Step 5: Update the database imports in `__init__` or top-level exports**

Make sure the three new models are importable. Check the bottom of `database.py` — if there's no `__all__`, the models are importable by name already (they're module-level classes). No action needed if that's the case.

- [ ] **Step 6: Commit**

```bash
git add backend/database.py
git commit -m "feat(db): add questionnaire models and agent welcome/closing fields"
```

---

## Task 2: Validation update

**Files:**
- Modify: `backend/validation.py:304`

- [ ] **Step 1: Update the Agent type validation pattern**

In `backend/validation.py`, line 304, change:

```python
    type: Optional[str] = Field("conversationnel", pattern="^(conversationnel|recherche_live)$")
```

to:

```python
    type: Optional[str] = Field("conversationnel", pattern="^(conversationnel|recherche_live|questionnaire)$")
```

- [ ] **Step 2: Commit**

```bash
git add backend/validation.py
git commit -m "feat(validation): allow questionnaire as agent type"
```

---

## Task 3: Pydantic schemas for questionnaire endpoints

**Files:**
- Create: `backend/schemas/questionnaires.py`

- [ ] **Step 1: Create the schemas file**

Create `backend/schemas/questionnaires.py`:

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add backend/schemas/questionnaires.py
git commit -m "feat(schemas): add pydantic models for questionnaire endpoints"
```

---

## Task 4: Questionnaire invitation email

**Files:**
- Modify: `backend/email_service.py`

- [ ] **Step 1: Add `send_questionnaire_invitation_email` function**

At the end of `backend/email_service.py` (after the last function), add:

```python
def send_questionnaire_invitation_email(
    to_email: str, questionnaire_name: str, company_name: str, respondent_name: str, questionnaire_url: str
):
    """Send a branded questionnaire invitation email with CTA button."""
    greeting = f"Bonjour {respondent_name}," if respondent_name else "Bonjour,"
    content = f"""
<h2 style="color:#1f2937; margin:0 0 16px 0; font-size:20px;">
  Vous &ecirc;tes invit&eacute;(e) &agrave; r&eacute;pondre &agrave; un questionnaire
</h2>
<p style="color:#4b5563; font-size:15px; line-height:1.6; margin:0 0 8px 0;">
  {greeting}
</p>
<p style="color:#4b5563; font-size:15px; line-height:1.6; margin:0 0 24px 0;">
  <strong>{company_name}</strong> vous invite &agrave; r&eacute;pondre au questionnaire
  <strong>&laquo;&nbsp;{questionnaire_name}&nbsp;&raquo;</strong>.
  Cliquez sur le bouton ci-dessous pour commencer.
</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <td align="center" style="padding:8px 0 24px 0;">
      <a href="{questionnaire_url}"
         style="display:inline-block; background:linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
                color:#ffffff; text-decoration:none; padding:14px 32px; border-radius:8px;
                font-size:15px; font-weight:600; letter-spacing:0.3px;">
        R&eacute;pondre au questionnaire
      </a>
    </td>
  </tr>
</table>
<p style="color:#9ca3af; font-size:13px; line-height:1.5; margin:0;">
  Ce lien est unique et personnel. Ne le partagez pas.
</p>"""

    html = _wrap_template(content, preheader=f"Questionnaire : {questionnaire_name}")
    send_email(to_email, f"Questionnaire : {questionnaire_name}", html)
```

- [ ] **Step 2: Commit**

```bash
git add backend/email_service.py
git commit -m "feat(email): add questionnaire invitation email template"
```

---

## Task 5: Backend questionnaire router — Question CRUD

**Files:**
- Create: `backend/routers/questionnaires.py`

- [ ] **Step 1: Create the router with question CRUD endpoints**

Create `backend/routers/questionnaires.py`:

```python
"""Questionnaire companion endpoints: question CRUD, invitations, responses, export."""

import json
import logging
import secrets
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth import verify_token
from database import (
    get_db,
    Agent,
    Document,
    DocumentChunk,
    QuestionnaireQuestion,
    QuestionnaireResponse,
    QuestionnaireAnswer,
)
from helpers.tenant import _get_caller_company_id
from schemas.questionnaires import (
    QuestionCreate,
    QuestionUpdate,
    QuestionOut,
    ReorderRequest,
    InviteRequest,
    ResponseSummary,
    ResponseDetail,
    AnswerOut,
    ExportRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_questionnaire_agent(agent_id: int, user_id: int, db: Session) -> Agent:
    """Fetch agent and verify it's a questionnaire type owned by the caller's company."""
    company_id = _get_caller_company_id(user_id, db)
    agent = db.query(Agent).filter(
        Agent.id == agent_id,
        Agent.company_id == company_id,
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.type != "questionnaire":
        raise HTTPException(status_code=400, detail="Agent is not a questionnaire type")
    return agent


# ── Question CRUD ──────────────────────────────────────────────

@router.get("/api/agents/{agent_id}/questions", response_model=List[QuestionOut])
async def list_questions(agent_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    agent = _get_questionnaire_agent(agent_id, int(user_id), db)
    questions = (
        db.query(QuestionnaireQuestion)
        .filter(QuestionnaireQuestion.agent_id == agent.id)
        .order_by(QuestionnaireQuestion.position)
        .all()
    )
    return questions


@router.post("/api/agents/{agent_id}/questions", response_model=QuestionOut)
async def create_question(agent_id: int, body: QuestionCreate, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    agent = _get_questionnaire_agent(agent_id, int(user_id), db)
    company_id = _get_caller_company_id(int(user_id), db)

    # Auto-assign position if not specified or 0
    if body.position == 0:
        max_pos = (
            db.query(QuestionnaireQuestion.position)
            .filter(QuestionnaireQuestion.agent_id == agent.id)
            .order_by(QuestionnaireQuestion.position.desc())
            .first()
        )
        body.position = (max_pos[0] + 1) if max_pos else 1

    q = QuestionnaireQuestion(
        agent_id=agent.id,
        company_id=company_id,
        question_text=body.question_text,
        question_type=body.question_type,
        options=body.options,
        position=body.position,
        required=body.required,
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


@router.patch("/api/agents/{agent_id}/questions/{question_id}", response_model=QuestionOut)
async def update_question(agent_id: int, question_id: int, body: QuestionUpdate, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    agent = _get_questionnaire_agent(agent_id, int(user_id), db)
    q = db.query(QuestionnaireQuestion).filter(
        QuestionnaireQuestion.id == question_id,
        QuestionnaireQuestion.agent_id == agent.id,
    ).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")

    for field, value in body.dict(exclude_unset=True).items():
        setattr(q, field, value)
    db.commit()
    db.refresh(q)
    return q


@router.delete("/api/agents/{agent_id}/questions/{question_id}")
async def delete_question(agent_id: int, question_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    agent = _get_questionnaire_agent(agent_id, int(user_id), db)
    q = db.query(QuestionnaireQuestion).filter(
        QuestionnaireQuestion.id == question_id,
        QuestionnaireQuestion.agent_id == agent.id,
    ).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    db.delete(q)
    db.commit()
    return {"detail": "Deleted"}


@router.put("/api/agents/{agent_id}/questions/reorder")
async def reorder_questions(agent_id: int, body: ReorderRequest, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    agent = _get_questionnaire_agent(agent_id, int(user_id), db)
    questions = (
        db.query(QuestionnaireQuestion)
        .filter(QuestionnaireQuestion.agent_id == agent.id)
        .all()
    )
    q_map = {q.id: q for q in questions}
    for idx, qid in enumerate(body.question_ids):
        if qid in q_map:
            q_map[qid].position = idx + 1
    db.commit()
    return {"detail": "Reordered"}
```

- [ ] **Step 2: Commit**

```bash
git add backend/routers/questionnaires.py
git commit -m "feat(api): add questionnaire question CRUD endpoints"
```

---

## Task 6: Backend questionnaire router — Invitations

**Files:**
- Modify: `backend/routers/questionnaires.py`

- [ ] **Step 1: Add the invite endpoint to the router**

Append to `backend/routers/questionnaires.py`:

```python
# ── Invitations ────────────────────────────────────────────────

@router.post("/api/agents/{agent_id}/invite")
async def invite_respondents(agent_id: int, body: InviteRequest, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    import os
    from email_service import send_questionnaire_invitation_email

    agent = _get_questionnaire_agent(agent_id, int(user_id), db)
    company_id = _get_caller_company_id(int(user_id), db)

    # Get company name for the email
    from database import Company
    company = db.query(Company).filter(Company.id == company_id).first()
    company_name = company.name if company else "TAIC"

    frontend_url = os.getenv("NEXT_PUBLIC_FRONTEND_URL", os.getenv("FRONTEND_URL", "http://localhost:3000"))
    created = []

    for i, email in enumerate(body.emails):
        email = email.strip().lower()
        # Skip if already invited
        existing = db.query(QuestionnaireResponse).filter(
            QuestionnaireResponse.agent_id == agent.id,
            QuestionnaireResponse.respondent_email == email,
        ).first()
        if existing:
            continue

        token = secrets.token_urlsafe(48)
        name = body.names[i] if body.names and i < len(body.names) else None

        response = QuestionnaireResponse(
            agent_id=agent.id,
            company_id=company_id,
            respondent_email=email,
            respondent_name=name,
            token=token,
            status="pending",
        )
        db.add(response)
        db.flush()

        questionnaire_url = f"{frontend_url}/questionnaire/{token}"
        try:
            send_questionnaire_invitation_email(
                to_email=email,
                questionnaire_name=agent.name,
                company_name=company_name,
                respondent_name=name or "",
                questionnaire_url=questionnaire_url,
            )
        except Exception as e:
            logger.error(f"Failed to send questionnaire invite to {email}: {e}")

        created.append({"email": email, "token": token})

    db.commit()
    return {"invited": len(created), "details": created}
```

- [ ] **Step 2: Commit**

```bash
git add backend/routers/questionnaires.py
git commit -m "feat(api): add questionnaire invitation endpoint with email sending"
```

---

## Task 7: Backend questionnaire router — Responses & PDF

**Files:**
- Modify: `backend/routers/questionnaires.py`

- [ ] **Step 1: Add response list and detail endpoints**

Append to `backend/routers/questionnaires.py`:

```python
# ── Responses ──────────────────────────────────────────────────

@router.get("/api/agents/{agent_id}/responses")
async def list_responses(
    agent_id: int,
    status: Optional[str] = Query(None),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    agent = _get_questionnaire_agent(agent_id, int(user_id), db)
    query = db.query(QuestionnaireResponse).filter(QuestionnaireResponse.agent_id == agent.id)
    if status:
        query = query.filter(QuestionnaireResponse.status == status)
    responses = query.order_by(QuestionnaireResponse.invited_at.desc()).all()

    total_invited = db.query(QuestionnaireResponse).filter(QuestionnaireResponse.agent_id == agent.id).count()
    total_completed = db.query(QuestionnaireResponse).filter(
        QuestionnaireResponse.agent_id == agent.id,
        QuestionnaireResponse.status == "completed",
    ).count()

    return {
        "total_invited": total_invited,
        "total_completed": total_completed,
        "responses": [
            ResponseSummary.from_orm(r).dict() for r in responses
        ],
    }


@router.get("/api/agents/{agent_id}/responses/{response_id}")
async def get_response_detail(agent_id: int, response_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    agent = _get_questionnaire_agent(agent_id, int(user_id), db)
    resp = db.query(QuestionnaireResponse).filter(
        QuestionnaireResponse.id == response_id,
        QuestionnaireResponse.agent_id == agent.id,
    ).first()
    if not resp:
        raise HTTPException(status_code=404, detail="Response not found")

    answers_out = []
    for ans in resp.answers:
        q = ans.question
        answers_out.append(AnswerOut(
            id=ans.id,
            question_id=q.id,
            question_text=q.question_text,
            question_type=q.question_type,
            answer_text=ans.answer_text,
            answered_at=ans.answered_at,
        ))

    return ResponseDetail(
        id=resp.id,
        respondent_email=resp.respondent_email,
        respondent_name=resp.respondent_name,
        status=resp.status,
        invited_at=resp.invited_at,
        started_at=resp.started_at,
        completed_at=resp.completed_at,
        answers=answers_out,
    ).dict()
```

- [ ] **Step 2: Add PDF download endpoint**

Append to `backend/routers/questionnaires.py`:

```python
@router.get("/api/agents/{agent_id}/responses/{response_id}/pdf")
async def download_response_pdf(agent_id: int, response_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    from fastapi.responses import Response as FastAPIResponse

    agent = _get_questionnaire_agent(agent_id, int(user_id), db)
    resp = db.query(QuestionnaireResponse).filter(
        QuestionnaireResponse.id == response_id,
        QuestionnaireResponse.agent_id == agent.id,
    ).first()
    if not resp:
        raise HTTPException(status_code=404, detail="Response not found")

    # Build HTML for PDF
    html_parts = [
        f"<h1>Questionnaire : {agent.name}</h1>",
        f"<h2>R&eacute;pondant : {resp.respondent_name or resp.respondent_email}</h2>",
        f"<p>Email : {resp.respondent_email}</p>",
        f"<p>Date : {resp.completed_at.strftime('%d/%m/%Y') if resp.completed_at else 'En cours'}</p>",
        "<hr>",
    ]
    for ans in resp.answers:
        q = ans.question
        html_parts.append(f"<h3>{q.question_text}</h3>")
        if q.question_type == "rating":
            html_parts.append(f"<p><strong>Note : {ans.answer_text}</strong></p>")
        elif q.question_type in ("single_choice", "multiple_choice"):
            html_parts.append(f"<p>{ans.answer_text}</p>")
        else:
            html_parts.append(f"<p>{ans.answer_text}</p>")

    full_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 700px; margin: 40px auto; color: #1f2937; }}
h1 {{ color: #6366f1; font-size: 24px; }}
h2 {{ color: #374151; font-size: 18px; }}
h3 {{ color: #4b5563; font-size: 16px; margin-top: 24px; }}
hr {{ border: none; border-top: 1px solid #e5e7eb; margin: 24px 0; }}
p {{ line-height: 1.6; }}
</style></head><body>{''.join(html_parts)}</body></html>"""

    try:
        import weasyprint
        pdf_bytes = weasyprint.HTML(string=full_html).write_pdf()
    except ImportError:
        # Fallback: return HTML if weasyprint not installed
        return FastAPIResponse(content=full_html, media_type="text/html")

    filename = f"questionnaire-{agent.name}-{resp.respondent_name or resp.respondent_email}.pdf"
    return FastAPIResponse(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

- [ ] **Step 3: Commit**

```bash
git add backend/routers/questionnaires.py
git commit -m "feat(api): add questionnaire response list, detail and PDF endpoints"
```

---

## Task 8: Backend questionnaire router — RAG Export

**Files:**
- Modify: `backend/routers/questionnaires.py`

- [ ] **Step 1: Add the export endpoint**

Append to `backend/routers/questionnaires.py`:

```python
# ── Export to RAG ──────────────────────────────────────────────

def _build_response_markdown(agent_name: str, resp: QuestionnaireResponse) -> str:
    """Build structured Markdown from a questionnaire response for RAG ingestion."""
    lines = [
        f"# Questionnaire : {agent_name}",
        f"## Répondant : {resp.respondent_name or 'Anonyme'} ({resp.respondent_email})",
        f"## Date : {resp.completed_at.strftime('%d/%m/%Y') if resp.completed_at else 'Non complété'}",
        "",
    ]
    for ans in resp.answers:
        q = ans.question
        lines.append(f"### {q.question_text}")
        if q.question_type == "rating":
            try:
                opts = json.loads(q.options) if q.options else {"min": 1, "max": 5}
                max_val = opts.get("max", 5)
            except (json.JSONDecodeError, AttributeError):
                max_val = 5
            lines.append(f"Note : {ans.answer_text}/{max_val}")
        elif q.question_type in ("single_choice", "multiple_choice"):
            lines.append(f"Choix : {ans.answer_text}")
        else:
            lines.append(ans.answer_text or "")
        lines.append("")
    return "\n".join(lines)


@router.post("/api/agents/{agent_id}/responses/export")
async def export_responses_to_rag(
    agent_id: int,
    body: ExportRequest,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    from rag_engine import process_document_for_user

    agent = _get_questionnaire_agent(agent_id, int(user_id), db)
    company_id = _get_caller_company_id(int(user_id), db)

    # Verify target agent exists and belongs to same company
    target = db.query(Agent).filter(
        Agent.id == body.target_agent_id,
        Agent.company_id == company_id,
        Agent.type.in_(["conversationnel", "actionnable"]),
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target agent not found or not a valid RAG agent")

    exported = []
    for rid in body.response_ids:
        resp = db.query(QuestionnaireResponse).filter(
            QuestionnaireResponse.id == rid,
            QuestionnaireResponse.agent_id == agent.id,
            QuestionnaireResponse.status == "completed",
        ).first()
        if not resp:
            continue

        markdown = _build_response_markdown(agent.name, resp)
        filename = f"Questionnaire - {agent.name} - {resp.respondent_name or resp.respondent_email}.md"

        # Create Document directly (bypass GCS upload — this is generated content, not a file)
        doc = Document(
            filename=filename,
            content=markdown,
            user_id=int(user_id),
            agent_id=target.id,
            company_id=company_id,
            document_type="rag",
        )
        db.add(doc)
        db.flush()

        # Chunk and embed
        from file_loader import chunk_text
        from mistral_embeddings import get_embeddings

        chunks = chunk_text(markdown)
        embeddings = get_embeddings(chunks)
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            db_chunk = DocumentChunk(
                document_id=doc.id,
                company_id=company_id,
                chunk_text=chunk,
                chunk_index=i,
            )
            if emb:
                db_chunk.embedding_vec = emb
            db.add(db_chunk)

        exported.append({"response_id": rid, "document_id": doc.id, "target_agent_id": target.id})

    db.commit()
    return {"exported": len(exported), "details": exported}
```

- [ ] **Step 2: Commit**

```bash
git add backend/routers/questionnaires.py
git commit -m "feat(api): add questionnaire response export to RAG pipeline"
```

---

## Task 9: Public questionnaire endpoints

**Files:**
- Modify: `backend/routers/public.py`
- Modify: `backend/schemas/questionnaires.py` (already has the schemas)

- [ ] **Step 1: Add public questionnaire endpoints to `public.py`**

Add imports at the top of `backend/routers/public.py`:

```python
from database import get_db, Agent, QuestionnaireQuestion, QuestionnaireResponse, QuestionnaireAnswer
from schemas.questionnaires import PublicQuestionnaireOut, QuestionOut, PublicAnswerSubmit
```

Then append the three public endpoints at the bottom of the file:

```python
##### Public questionnaire endpoints (no auth) #####


@router.get("/questionnaire/{token}")
async def public_get_questionnaire(token: str, request: Request, db: Session = Depends(get_db)):
    """Get questionnaire data for a respondent via their unique token."""
    ip = request.client.host if hasattr(request, "client") and request.client else "unknown"
    if not _check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")

    resp = db.query(QuestionnaireResponse).filter(QuestionnaireResponse.token == token).first()
    if not resp:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    if resp.status == "completed":
        return {"status": "completed", "message": "Vous avez déjà répondu à ce questionnaire. Merci !"}

    agent = db.query(Agent).filter(Agent.id == resp.agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Questionnaire not found")

    questions = (
        db.query(QuestionnaireQuestion)
        .filter(QuestionnaireQuestion.agent_id == agent.id)
        .order_by(QuestionnaireQuestion.position)
        .all()
    )

    # Get already-answered question IDs for this response
    answered_ids = {
        a.question_id
        for a in db.query(QuestionnaireAnswer.question_id).filter(
            QuestionnaireAnswer.response_id == resp.id
        ).all()
    }

    return {
        "status": resp.status,
        "agent_name": agent.name,
        "welcome_message": agent.welcome_message,
        "closing_message": agent.closing_message,
        "respondent_name": resp.respondent_name,
        "questions": [
            {
                "id": q.id,
                "question_text": q.question_text,
                "question_type": q.question_type,
                "options": q.options,
                "position": q.position,
                "required": q.required,
            }
            for q in questions
        ],
        "answered_question_ids": list(answered_ids),
    }


@router.post("/questionnaire/{token}/answer")
async def public_submit_answer(token: str, body: PublicAnswerSubmit, request: Request, db: Session = Depends(get_db)):
    """Submit a single answer to a questionnaire question."""
    ip = request.client.host if hasattr(request, "client") and request.client else "unknown"
    if not _check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")

    resp = db.query(QuestionnaireResponse).filter(QuestionnaireResponse.token == token).first()
    if not resp:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    if resp.status == "completed":
        raise HTTPException(status_code=400, detail="Questionnaire already completed")

    # Verify question belongs to this questionnaire's agent
    q = db.query(QuestionnaireQuestion).filter(
        QuestionnaireQuestion.id == body.question_id,
        QuestionnaireQuestion.agent_id == resp.agent_id,
    ).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")

    # Mark as in_progress on first answer
    if resp.status == "pending":
        resp.status = "in_progress"
        resp.started_at = datetime.utcnow()

    # Upsert answer
    existing = db.query(QuestionnaireAnswer).filter(
        QuestionnaireAnswer.response_id == resp.id,
        QuestionnaireAnswer.question_id == q.id,
    ).first()
    if existing:
        existing.answer_text = body.answer_text
        existing.answered_at = datetime.utcnow()
    else:
        ans = QuestionnaireAnswer(
            response_id=resp.id,
            question_id=q.id,
            company_id=resp.company_id,
            answer_text=body.answer_text,
            answered_at=datetime.utcnow(),
        )
        db.add(ans)

    db.commit()
    return {"detail": "Answer saved"}


@router.post("/questionnaire/{token}/complete")
async def public_complete_questionnaire(token: str, request: Request, db: Session = Depends(get_db)):
    """Mark a questionnaire as completed and generate closing message."""
    ip = request.client.host if hasattr(request, "client") and request.client else "unknown"
    if not _check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")

    resp = db.query(QuestionnaireResponse).filter(QuestionnaireResponse.token == token).first()
    if not resp:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    if resp.status == "completed":
        return {"status": "already_completed", "message": "Déjà complété."}

    resp.status = "completed"
    resp.completed_at = datetime.utcnow()
    db.commit()

    # Generate closing message via Mistral
    agent = db.query(Agent).filter(Agent.id == resp.agent_id).first()
    closing_message = agent.closing_message or "Merci pour vos réponses !"
    try:
        from mistral_client import generate_text
        prompt = (
            f"Tu es un assistant professionnel. Le répondant vient de compléter le questionnaire "
            f"'{agent.name}'. Génère un court message de remerciement chaleureux et professionnel "
            f"en français (2-3 phrases max). Base-toi sur cette consigne : {closing_message}"
        )
        closing_message = generate_text(prompt, model_name="mistral-small-latest", max_tokens=200, temperature=0.7)
    except Exception as e:
        logger.warning(f"Mistral closing message failed, using fallback: {e}")

    return {"status": "completed", "closing_message": closing_message}
```

- [ ] **Step 2: Commit**

```bash
git add backend/routers/public.py
git commit -m "feat(api): add public questionnaire endpoints (get, answer, complete)"
```

---

## Task 10: Register questionnaire router in main.py

**Files:**
- Modify: `backend/main.py:502-544`

- [ ] **Step 1: Add the import and router registration**

After line 520 (the action_executions import), add:

```python
from routers.questionnaires import router as questionnaires_router  # noqa: E402
```

After line 544 (the last `app.include_router`), add:

```python
app.include_router(questionnaires_router)
```

- [ ] **Step 2: Commit**

```bash
git add backend/main.py
git commit -m "feat(main): register questionnaire router"
```

---

## Task 11: Frontend i18n — Questionnaire translations

**Files:**
- Create: `frontend/public/locales/fr/questionnaire.json`
- Create: `frontend/public/locales/en/questionnaire.json`

- [ ] **Step 1: Create French translations**

Create `frontend/public/locales/fr/questionnaire.json`:

```json
{
  "type": {
    "name": "Questionnaire",
    "description": "Collecte des réponses via un chat conversationnel"
  },
  "builder": {
    "title": "Questions",
    "addQuestion": "Ajouter une question",
    "welcomeMessage": "Message d'accueil",
    "welcomePlaceholder": "Ex: Enquête de satisfaction client Q2 2026",
    "closingMessage": "Message de conclusion",
    "closingPlaceholder": "Ex: Merci pour votre temps !",
    "questionPlaceholder": "Tapez votre question...",
    "questionType": "Type de question",
    "types": {
      "open": "Texte libre",
      "single_choice": "Choix unique",
      "multiple_choice": "Choix multiple",
      "rating": "Note"
    },
    "optionPlaceholder": "Option {{n}}",
    "addOption": "Ajouter une option",
    "required": "Obligatoire",
    "ratingMin": "Min",
    "ratingMax": "Max",
    "noQuestions": "Aucune question. Ajoutez votre première question."
  },
  "invitations": {
    "title": "Invitations",
    "emailPlaceholder": "email@exemple.com",
    "namePlaceholder": "Nom (optionnel)",
    "send": "Envoyer les invitations",
    "addEmail": "Ajouter",
    "sent": "{{count}} invitation(s) envoyée(s)",
    "status": {
      "pending": "En attente",
      "in_progress": "En cours",
      "completed": "Complété"
    }
  },
  "responses": {
    "title": "Réponses",
    "counter": "{{completed}} réponses / {{total}} invitations",
    "filterAll": "Toutes",
    "filterCompleted": "Complétées",
    "filterPending": "En attente",
    "noResponses": "Aucune réponse pour le moment.",
    "downloadPdf": "Télécharger PDF",
    "exportToAgent": "Exporter vers un agent",
    "selectAgent": "Choisir un agent",
    "exportButton": "Exporter",
    "exportSuccess": "{{count}} réponse(s) exportée(s) avec succès",
    "backToList": "Retour à la liste"
  },
  "public": {
    "startButton": "Commencer",
    "nextButton": "Suivant",
    "validateChoices": "Valider",
    "completed": "Vous avez déjà répondu à ce questionnaire. Merci !",
    "notFound": "Questionnaire introuvable.",
    "inputPlaceholder": "Tapez votre réponse..."
  },
  "tabs": {
    "questions": "Questions",
    "invitations": "Invitations",
    "responses": "Réponses"
  }
}
```

- [ ] **Step 2: Create English translations**

Create `frontend/public/locales/en/questionnaire.json`:

```json
{
  "type": {
    "name": "Questionnaire",
    "description": "Collect responses through a conversational chat"
  },
  "builder": {
    "title": "Questions",
    "addQuestion": "Add a question",
    "welcomeMessage": "Welcome message",
    "welcomePlaceholder": "E.g.: Customer satisfaction survey Q2 2026",
    "closingMessage": "Closing message",
    "closingPlaceholder": "E.g.: Thank you for your time!",
    "questionPlaceholder": "Type your question...",
    "questionType": "Question type",
    "types": {
      "open": "Free text",
      "single_choice": "Single choice",
      "multiple_choice": "Multiple choice",
      "rating": "Rating"
    },
    "optionPlaceholder": "Option {{n}}",
    "addOption": "Add an option",
    "required": "Required",
    "ratingMin": "Min",
    "ratingMax": "Max",
    "noQuestions": "No questions yet. Add your first question."
  },
  "invitations": {
    "title": "Invitations",
    "emailPlaceholder": "email@example.com",
    "namePlaceholder": "Name (optional)",
    "send": "Send invitations",
    "addEmail": "Add",
    "sent": "{{count}} invitation(s) sent",
    "status": {
      "pending": "Pending",
      "in_progress": "In progress",
      "completed": "Completed"
    }
  },
  "responses": {
    "title": "Responses",
    "counter": "{{completed}} responses / {{total}} invitations",
    "filterAll": "All",
    "filterCompleted": "Completed",
    "filterPending": "Pending",
    "noResponses": "No responses yet.",
    "downloadPdf": "Download PDF",
    "exportToAgent": "Export to agent",
    "selectAgent": "Select an agent",
    "exportButton": "Export",
    "exportSuccess": "{{count}} response(s) exported successfully",
    "backToList": "Back to list"
  },
  "public": {
    "startButton": "Start",
    "nextButton": "Next",
    "validateChoices": "Confirm",
    "completed": "You have already answered this questionnaire. Thank you!",
    "notFound": "Questionnaire not found.",
    "inputPlaceholder": "Type your answer..."
  },
  "tabs": {
    "questions": "Questions",
    "invitations": "Invitations",
    "responses": "Responses"
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/public/locales/fr/questionnaire.json frontend/public/locales/en/questionnaire.json
git commit -m "feat(i18n): add questionnaire translations (fr + en)"
```

---

## Task 12: Frontend — QuestionCard component

**Files:**
- Create: `frontend/components/questionnaire/QuestionCard.js`

- [ ] **Step 1: Create the QuestionCard component**

Create `frontend/components/questionnaire/QuestionCard.js`:

```jsx
import { useState } from 'react';
import { useTranslation } from 'next-i18next';
import { GripVertical, Trash2, ChevronDown, ChevronUp, Plus, X, Star, ToggleLeft, ToggleRight } from 'lucide-react';

const QUESTION_TYPES = ['open', 'single_choice', 'multiple_choice', 'rating'];

export default function QuestionCard({ question, index, onChange, onDelete }) {
  const { t } = useTranslation('questionnaire');
  const [expanded, setExpanded] = useState(true);

  const parsedOptions = (() => {
    if (!question.options) return [];
    try { return JSON.parse(question.options); } catch { return []; }
  })();

  const ratingConfig = (() => {
    if (question.question_type !== 'rating' || !question.options) return { min: 1, max: 5 };
    try { return JSON.parse(question.options); } catch { return { min: 1, max: 5 }; }
  })();

  const updateField = (field, value) => {
    onChange({ ...question, [field]: value });
  };

  const updateOptions = (opts) => {
    updateField('options', JSON.stringify(opts));
  };

  const updateRatingConfig = (key, value) => {
    const cfg = { ...ratingConfig, [key]: parseInt(value) || 1 };
    updateField('options', JSON.stringify(cfg));
  };

  const addOption = () => {
    updateOptions([...parsedOptions, '']);
  };

  const removeOption = (idx) => {
    updateOptions(parsedOptions.filter((_, i) => i !== idx));
  };

  const setOptionValue = (idx, value) => {
    const next = [...parsedOptions];
    next[idx] = value;
    updateOptions(next);
  };

  return (
    <div className="border border-gray-200 rounded-card bg-white shadow-subtle">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
        <GripVertical className="w-4 h-4 text-gray-300 cursor-grab" />
        <span className="text-sm font-semibold text-gray-500 w-6">{index + 1}.</span>
        <span className="flex-1 text-sm font-medium text-gray-800 truncate">
          {question.question_text || t('builder.questionPlaceholder')}
        </span>
        <span className="text-xs px-2 py-0.5 rounded-full bg-primary-50 text-primary-700 font-medium">
          {t(`builder.types.${question.question_type}`)}
        </span>
        <button onClick={() => setExpanded(!expanded)} className="p-1 text-gray-400 hover:text-gray-600">
          {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
        <button onClick={onDelete} className="p-1 text-gray-400 hover:text-red-500">
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      {/* Body */}
      {expanded && (
        <div className="px-4 py-4 space-y-4">
          {/* Question text */}
          <div>
            <input
              type="text"
              value={question.question_text}
              onChange={(e) => updateField('question_text', e.target.value)}
              placeholder={t('builder.questionPlaceholder')}
              className="w-full px-3 py-2 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
            />
          </div>

          {/* Type selector */}
          <div className="flex items-center gap-3">
            <label className="text-sm text-gray-600 font-medium">{t('builder.questionType')}</label>
            <select
              value={question.question_type}
              onChange={(e) => {
                const newType = e.target.value;
                const update = { ...question, question_type: newType };
                if (newType === 'rating') {
                  update.options = JSON.stringify({ min: 1, max: 5 });
                } else if (newType === 'open') {
                  update.options = null;
                } else if (!parsedOptions.length || typeof parsedOptions !== 'object' || !Array.isArray(parsedOptions)) {
                  update.options = JSON.stringify(['']);
                }
                onChange(update);
              }}
              className="px-3 py-1.5 border border-gray-200 rounded-input text-sm bg-white focus:ring-2 focus:ring-primary-500"
            >
              {QUESTION_TYPES.map((qt) => (
                <option key={qt} value={qt}>{t(`builder.types.${qt}`)}</option>
              ))}
            </select>

            {/* Required toggle */}
            <button
              onClick={() => updateField('required', !question.required)}
              className="ml-auto flex items-center gap-1.5 text-sm text-gray-600"
            >
              {question.required ? (
                <ToggleRight className="w-5 h-5 text-primary-600" />
              ) : (
                <ToggleLeft className="w-5 h-5 text-gray-400" />
              )}
              {t('builder.required')}
            </button>
          </div>

          {/* Options editor (for single_choice / multiple_choice) */}
          {(question.question_type === 'single_choice' || question.question_type === 'multiple_choice') && (
            <div className="space-y-2">
              {parsedOptions.map((opt, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <span className="text-xs text-gray-400 w-5">{idx + 1}.</span>
                  <input
                    type="text"
                    value={opt}
                    onChange={(e) => setOptionValue(idx, e.target.value)}
                    placeholder={t('builder.optionPlaceholder', { n: idx + 1 })}
                    className="flex-1 px-3 py-1.5 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500"
                  />
                  <button onClick={() => removeOption(idx)} className="p-1 text-gray-400 hover:text-red-500">
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))}
              <button onClick={addOption} className="flex items-center gap-1 text-sm text-primary-600 hover:text-primary-700 font-medium">
                <Plus className="w-3.5 h-3.5" />
                {t('builder.addOption')}
              </button>
            </div>
          )}

          {/* Rating config */}
          {question.question_type === 'rating' && (
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <label className="text-sm text-gray-600">{t('builder.ratingMin')}</label>
                <input
                  type="number"
                  value={ratingConfig.min}
                  onChange={(e) => updateRatingConfig('min', e.target.value)}
                  className="w-16 px-2 py-1.5 border border-gray-200 rounded-input text-sm text-center"
                  min="0" max="10"
                />
              </div>
              <div className="flex items-center gap-2">
                <label className="text-sm text-gray-600">{t('builder.ratingMax')}</label>
                <input
                  type="number"
                  value={ratingConfig.max}
                  onChange={(e) => updateRatingConfig('max', e.target.value)}
                  className="w-16 px-2 py-1.5 border border-gray-200 rounded-input text-sm text-center"
                  min="1" max="10"
                />
              </div>
              <div className="flex items-center gap-1 ml-4">
                {Array.from({ length: ratingConfig.max - ratingConfig.min + 1 }, (_, i) => (
                  <Star key={i} className="w-5 h-5 text-yellow-400 fill-yellow-400" />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/components/questionnaire/QuestionCard.js
git commit -m "feat(ui): add QuestionCard component for questionnaire builder"
```

---

## Task 13: Frontend — QuestionBuilder component

**Files:**
- Create: `frontend/components/questionnaire/QuestionBuilder.js`

- [ ] **Step 1: Create the QuestionBuilder component**

Create `frontend/components/questionnaire/QuestionBuilder.js`:

```jsx
import { useState, useEffect } from 'react';
import { useTranslation } from 'next-i18next';
import { Plus, ClipboardList } from 'lucide-react';
import QuestionCard from './QuestionCard';
import api from '../../lib/api';
import toast from 'react-hot-toast';

export default function QuestionBuilder({ agentId, welcomeMessage, closingMessage, onWelcomeChange, onClosingChange }) {
  const { t } = useTranslation('questionnaire');
  const [questions, setQuestions] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (agentId) loadQuestions();
  }, [agentId]);

  const loadQuestions = async () => {
    try {
      setLoading(true);
      const res = await api.get(`/api/agents/${agentId}/questions`);
      setQuestions(res.data);
    } catch (err) {
      console.error('Failed to load questions:', err);
    } finally {
      setLoading(false);
    }
  };

  const addQuestion = async () => {
    try {
      const res = await api.post(`/api/agents/${agentId}/questions`, {
        question_text: '',
        question_type: 'open',
        required: true,
      });
      setQuestions([...questions, res.data]);
    } catch (err) {
      toast.error('Failed to add question');
    }
  };

  const updateQuestion = async (index, updated) => {
    const q = updated;
    try {
      await api.patch(`/api/agents/${agentId}/questions/${q.id}`, {
        question_text: q.question_text,
        question_type: q.question_type,
        options: q.options,
        required: q.required,
      });
      const next = [...questions];
      next[index] = q;
      setQuestions(next);
    } catch (err) {
      toast.error('Failed to update question');
    }
  };

  const deleteQuestion = async (index) => {
    const q = questions[index];
    try {
      await api.delete(`/api/agents/${agentId}/questions/${q.id}`);
      setQuestions(questions.filter((_, i) => i !== index));
    } catch (err) {
      toast.error('Failed to delete question');
    }
  };

  return (
    <div className="space-y-6">
      {/* Welcome message */}
      <div>
        <label className="block text-sm font-semibold text-gray-700 mb-2">{t('builder.welcomeMessage')}</label>
        <input
          type="text"
          value={welcomeMessage || ''}
          onChange={(e) => onWelcomeChange(e.target.value)}
          placeholder={t('builder.welcomePlaceholder')}
          className="w-full px-4 py-2.5 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
        />
      </div>

      {/* Questions list */}
      <div>
        <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
          <ClipboardList className="w-4 h-4 text-primary-600" />
          {t('builder.title')} ({questions.length})
        </h3>
        {questions.length === 0 && !loading ? (
          <div className="text-center py-8 border-2 border-dashed border-gray-200 rounded-card">
            <ClipboardList className="w-10 h-10 text-gray-300 mx-auto mb-2" />
            <p className="text-sm text-gray-500">{t('builder.noQuestions')}</p>
          </div>
        ) : (
          <div className="space-y-3">
            {questions.map((q, idx) => (
              <QuestionCard
                key={q.id}
                question={q}
                index={idx}
                onChange={(updated) => updateQuestion(idx, updated)}
                onDelete={() => deleteQuestion(idx)}
              />
            ))}
          </div>
        )}
        <button
          onClick={addQuestion}
          className="mt-3 flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-primary-600 border border-primary-200 rounded-button hover:bg-primary-50 transition-colors w-full justify-center"
        >
          <Plus className="w-4 h-4" />
          {t('builder.addQuestion')}
        </button>
      </div>

      {/* Closing message */}
      <div>
        <label className="block text-sm font-semibold text-gray-700 mb-2">{t('builder.closingMessage')}</label>
        <input
          type="text"
          value={closingMessage || ''}
          onChange={(e) => onClosingChange(e.target.value)}
          placeholder={t('builder.closingPlaceholder')}
          className="w-full px-4 py-2.5 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/components/questionnaire/QuestionBuilder.js
git commit -m "feat(ui): add QuestionBuilder component with CRUD operations"
```

---

## Task 14: Frontend — InvitationsTab component

**Files:**
- Create: `frontend/components/questionnaire/InvitationsTab.js`

- [ ] **Step 1: Create the InvitationsTab component**

Create `frontend/components/questionnaire/InvitationsTab.js`:

```jsx
import { useState, useEffect } from 'react';
import { useTranslation } from 'next-i18next';
import { Send, Plus, Mail, X, Clock, CheckCircle, Loader2 } from 'lucide-react';
import api from '../../lib/api';
import toast from 'react-hot-toast';

const STATUS_COLORS = {
  pending: 'bg-yellow-100 text-yellow-700',
  in_progress: 'bg-blue-100 text-blue-700',
  completed: 'bg-green-100 text-green-700',
};

export default function InvitationsTab({ agentId }) {
  const { t } = useTranslation('questionnaire');
  const [responses, setResponses] = useState([]);
  const [stats, setStats] = useState({ total_invited: 0, total_completed: 0 });
  const [newEmails, setNewEmails] = useState([{ email: '', name: '' }]);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (agentId) loadResponses();
  }, [agentId]);

  const loadResponses = async () => {
    try {
      const res = await api.get(`/api/agents/${agentId}/responses`);
      setResponses(res.data.responses);
      setStats({ total_invited: res.data.total_invited, total_completed: res.data.total_completed });
    } catch (err) {
      console.error('Failed to load responses:', err);
    }
  };

  const addEmailRow = () => {
    setNewEmails([...newEmails, { email: '', name: '' }]);
  };

  const removeEmailRow = (idx) => {
    setNewEmails(newEmails.filter((_, i) => i !== idx));
  };

  const updateEmailRow = (idx, field, value) => {
    const next = [...newEmails];
    next[idx] = { ...next[idx], [field]: value };
    setNewEmails(next);
  };

  const sendInvitations = async () => {
    const validEmails = newEmails.filter(e => e.email.trim());
    if (validEmails.length === 0) return;

    setSending(true);
    try {
      const res = await api.post(`/api/agents/${agentId}/invite`, {
        emails: validEmails.map(e => e.email.trim()),
        names: validEmails.map(e => e.name.trim() || null),
      });
      toast.success(t('invitations.sent', { count: res.data.invited }));
      setNewEmails([{ email: '', name: '' }]);
      loadResponses();
    } catch (err) {
      toast.error('Failed to send invitations');
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Add new invitations */}
      <div className="bg-white border border-gray-200 rounded-card p-5">
        <h3 className="text-sm font-semibold text-gray-800 mb-4 flex items-center gap-2">
          <Mail className="w-4 h-4 text-primary-600" />
          {t('invitations.title')}
        </h3>
        <div className="space-y-2">
          {newEmails.map((row, idx) => (
            <div key={idx} className="flex items-center gap-2">
              <input
                type="email"
                value={row.email}
                onChange={(e) => updateEmailRow(idx, 'email', e.target.value)}
                placeholder={t('invitations.emailPlaceholder')}
                className="flex-1 px-3 py-2 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500"
              />
              <input
                type="text"
                value={row.name}
                onChange={(e) => updateEmailRow(idx, 'name', e.target.value)}
                placeholder={t('invitations.namePlaceholder')}
                className="w-40 px-3 py-2 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500"
              />
              {newEmails.length > 1 && (
                <button onClick={() => removeEmailRow(idx)} className="p-1 text-gray-400 hover:text-red-500">
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>
          ))}
        </div>
        <div className="flex items-center gap-3 mt-3">
          <button onClick={addEmailRow} className="flex items-center gap-1 text-sm text-gray-600 hover:text-gray-800">
            <Plus className="w-3.5 h-3.5" />
            {t('invitations.addEmail')}
          </button>
          <button
            onClick={sendInvitations}
            disabled={sending || !newEmails.some(e => e.email.trim())}
            className="ml-auto flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-button text-sm font-medium hover:bg-primary-700 disabled:opacity-50 transition-colors"
          >
            {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            {t('invitations.send')}
          </button>
        </div>
      </div>

      {/* Invitation list */}
      {responses.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-card overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-100 bg-gray-50">
            <p className="text-sm text-gray-600">
              {t('responses.counter', { completed: stats.total_completed, total: stats.total_invited })}
            </p>
          </div>
          <div className="divide-y divide-gray-100">
            {responses.map((r) => (
              <div key={r.id} className="flex items-center px-5 py-3">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-800 truncate">{r.respondent_name || r.respondent_email}</p>
                  {r.respondent_name && <p className="text-xs text-gray-500">{r.respondent_email}</p>}
                </div>
                <span className={`px-2.5 py-0.5 text-xs font-medium rounded-full ${STATUS_COLORS[r.status]}`}>
                  {t(`invitations.status.${r.status}`)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/components/questionnaire/InvitationsTab.js
git commit -m "feat(ui): add InvitationsTab component for questionnaire"
```

---

## Task 15: Frontend — ResponsesTab + ExportModal components

**Files:**
- Create: `frontend/components/questionnaire/ResponsesTab.js`
- Create: `frontend/components/questionnaire/ExportModal.js`

- [ ] **Step 1: Create the ExportModal component**

Create `frontend/components/questionnaire/ExportModal.js`:

```jsx
import { useState, useEffect } from 'react';
import { useTranslation } from 'next-i18next';
import { X, Upload, Bot, Loader2 } from 'lucide-react';
import api from '../../lib/api';
import toast from 'react-hot-toast';

export default function ExportModal({ agentId, responseIds, onClose }) {
  const { t } = useTranslation('questionnaire');
  const [agents, setAgents] = useState([]);
  const [targetAgentId, setTargetAgentId] = useState(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    loadAgents();
  }, []);

  const loadAgents = async () => {
    try {
      const res = await api.get('/api/agents');
      const ragAgents = (res.data || []).filter(
        (a) => (a.type === 'conversationnel' || a.type === 'actionnable') && a.id !== agentId
      );
      setAgents(ragAgents);
      if (ragAgents.length > 0) setTargetAgentId(ragAgents[0].id);
    } catch (err) {
      console.error('Failed to load agents:', err);
    }
  };

  const handleExport = async () => {
    if (!targetAgentId) return;
    setExporting(true);
    try {
      const res = await api.post(`/api/agents/${agentId}/responses/export`, {
        response_ids: responseIds,
        target_agent_id: targetAgentId,
      });
      toast.success(t('responses.exportSuccess', { count: res.data.exported }));
      onClose();
    } catch (err) {
      toast.error('Export failed');
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4 z-50 animate-fade-in">
      <div className="bg-white rounded-card shadow-floating max-w-md w-full animate-scale-in">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h3 className="text-lg font-heading font-bold text-gray-900">{t('responses.exportToAgent')}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-5 h-5" /></button>
        </div>
        <div className="px-6 py-5 space-y-4">
          <p className="text-sm text-gray-600">
            {responseIds.length} réponse(s) sélectionnée(s)
          </p>
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">{t('responses.selectAgent')}</label>
            <select
              value={targetAgentId || ''}
              onChange={(e) => setTargetAgentId(parseInt(e.target.value))}
              className="w-full px-3 py-2.5 border border-gray-200 rounded-input text-sm bg-white focus:ring-2 focus:ring-primary-500"
            >
              {agents.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">Annuler</button>
          <button
            onClick={handleExport}
            disabled={exporting || !targetAgentId}
            className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-button text-sm font-medium hover:bg-primary-700 disabled:opacity-50"
          >
            {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
            {t('responses.exportButton')}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create the ResponsesTab component**

Create `frontend/components/questionnaire/ResponsesTab.js`:

```jsx
import { useState, useEffect } from 'react';
import { useTranslation } from 'next-i18next';
import { Download, Upload, ArrowLeft, Star, CheckSquare, Loader2 } from 'lucide-react';
import api, { getApiUrl } from '../../lib/api';
import ExportModal from './ExportModal';

const STATUS_COLORS = {
  pending: 'bg-yellow-100 text-yellow-700',
  in_progress: 'bg-blue-100 text-blue-700',
  completed: 'bg-green-100 text-green-700',
};

export default function ResponsesTab({ agentId }) {
  const { t } = useTranslation('questionnaire');
  const [responses, setResponses] = useState([]);
  const [stats, setStats] = useState({ total_invited: 0, total_completed: 0 });
  const [filter, setFilter] = useState(null);
  const [selectedDetail, setSelectedDetail] = useState(null);
  const [detailData, setDetailData] = useState(null);
  const [selectedIds, setSelectedIds] = useState([]);
  const [showExportModal, setShowExportModal] = useState(false);

  useEffect(() => {
    if (agentId) loadResponses();
  }, [agentId, filter]);

  const loadResponses = async () => {
    try {
      const params = filter ? `?status=${filter}` : '';
      const res = await api.get(`/api/agents/${agentId}/responses${params}`);
      setResponses(res.data.responses);
      setStats({ total_invited: res.data.total_invited, total_completed: res.data.total_completed });
    } catch (err) {
      console.error('Failed to load responses:', err);
    }
  };

  const loadDetail = async (responseId) => {
    try {
      const res = await api.get(`/api/agents/${agentId}/responses/${responseId}`);
      setDetailData(res.data);
      setSelectedDetail(responseId);
    } catch (err) {
      console.error('Failed to load response detail:', err);
    }
  };

  const toggleSelect = (id) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const downloadPdf = (responseId) => {
    window.open(`${getApiUrl()}/api/agents/${agentId}/responses/${responseId}/pdf`, '_blank');
  };

  // Detail view
  if (selectedDetail && detailData) {
    return (
      <div className="space-y-4">
        <button onClick={() => { setSelectedDetail(null); setDetailData(null); }} className="flex items-center gap-1 text-sm text-primary-600 hover:text-primary-700">
          <ArrowLeft className="w-4 h-4" />
          {t('responses.backToList')}
        </button>
        <div className="bg-white border border-gray-200 rounded-card p-5">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-900">{detailData.respondent_name || detailData.respondent_email}</h3>
              {detailData.respondent_name && <p className="text-sm text-gray-500">{detailData.respondent_email}</p>}
            </div>
            <div className="flex gap-2">
              <button onClick={() => downloadPdf(detailData.id)} className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-200 rounded-button hover:bg-gray-50">
                <Download className="w-4 h-4" />
                {t('responses.downloadPdf')}
              </button>
              <button onClick={() => { setSelectedIds([detailData.id]); setShowExportModal(true); }} className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-primary-600 text-white rounded-button hover:bg-primary-700">
                <Upload className="w-4 h-4" />
                {t('responses.exportToAgent')}
              </button>
            </div>
          </div>
          <div className="space-y-4">
            {detailData.answers.map((ans) => (
              <div key={ans.id} className="border-b border-gray-100 pb-3">
                <p className="text-sm font-semibold text-gray-700 mb-1">{ans.question_text}</p>
                {ans.question_type === 'rating' ? (
                  <div className="flex items-center gap-1">
                    {Array.from({ length: parseInt(ans.answer_text) || 0 }, (_, i) => (
                      <Star key={i} className="w-4 h-4 text-yellow-400 fill-yellow-400" />
                    ))}
                    <span className="text-sm text-gray-500 ml-2">{ans.answer_text}</span>
                  </div>
                ) : (
                  <p className="text-sm text-gray-600">{ans.answer_text}</p>
                )}
              </div>
            ))}
          </div>
        </div>
        {showExportModal && (
          <ExportModal agentId={agentId} responseIds={selectedIds} onClose={() => setShowExportModal(false)} />
        )}
      </div>
    );
  }

  // List view
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-600">
          {t('responses.counter', { completed: stats.total_completed, total: stats.total_invited })}
        </p>
        <div className="flex gap-2">
          {selectedIds.length > 0 && (
            <button onClick={() => setShowExportModal(true)} className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-primary-600 text-white rounded-button hover:bg-primary-700">
              <Upload className="w-4 h-4" />
              {t('responses.exportToAgent')} ({selectedIds.length})
            </button>
          )}
        </div>
      </div>
      {/* Filters */}
      <div className="flex gap-2">
        {[null, 'completed', 'pending'].map((f) => (
          <button
            key={f || 'all'}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 text-sm rounded-button font-medium transition-colors ${
              filter === f ? 'bg-primary-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {f === null ? t('responses.filterAll') : t(`responses.filter${f.charAt(0).toUpperCase() + f.slice(1)}`)}
          </button>
        ))}
      </div>
      {/* Response list */}
      {responses.length === 0 ? (
        <div className="text-center py-12 text-gray-500 text-sm">{t('responses.noResponses')}</div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-card overflow-hidden divide-y divide-gray-100">
          {responses.map((r) => (
            <div key={r.id} className="flex items-center px-5 py-3 hover:bg-gray-50 cursor-pointer" onClick={() => r.status === 'completed' && loadDetail(r.id)}>
              <input
                type="checkbox"
                checked={selectedIds.includes(r.id)}
                onChange={(e) => { e.stopPropagation(); toggleSelect(r.id); }}
                className="mr-3 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                disabled={r.status !== 'completed'}
              />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-800 truncate">{r.respondent_name || r.respondent_email}</p>
                {r.respondent_name && <p className="text-xs text-gray-500">{r.respondent_email}</p>}
              </div>
              {r.completed_at && (
                <span className="text-xs text-gray-400 mr-3">
                  {new Date(r.completed_at).toLocaleDateString('fr-FR')}
                </span>
              )}
              <span className={`px-2.5 py-0.5 text-xs font-medium rounded-full ${STATUS_COLORS[r.status]}`}>
                {t(`invitations.status.${r.status}`)}
              </span>
            </div>
          ))}
        </div>
      )}
      {showExportModal && (
        <ExportModal agentId={agentId} responseIds={selectedIds} onClose={() => { setShowExportModal(false); setSelectedIds([]); }} />
      )}
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/components/questionnaire/ResponsesTab.js frontend/components/questionnaire/ExportModal.js
git commit -m "feat(ui): add ResponsesTab and ExportModal components"
```

---

## Task 16: Frontend — Modify agents.js for questionnaire type

**Files:**
- Modify: `frontend/pages/agents.js`

- [ ] **Step 1: Add `questionnaire` to the agent type selector**

In `frontend/pages/agents.js`, find the type `<select>` (around line 370-376). After the `actionnable` option, add:

```jsx
<option value="questionnaire">{t('agents:types.questionnaire.name')} - {t('agents:types.questionnaire.description')}</option>
```

- [ ] **Step 2: Add `welcome_message` and `closing_message` to the form state**

In `frontend/pages/agents.js`, find the `form` state initialization (line 31). Add `welcome_message: ''` and `closing_message: ''` to the initial state object. Do the same for every `setForm({ ... })` reset call (lines 261, 683, 738).

- [ ] **Step 3: Conditionally render QuestionBuilder for questionnaire type**

In `frontend/pages/agents.js`, add the import at the top:

```jsx
import QuestionBuilder from '../components/questionnaire/QuestionBuilder';
import InvitationsTab from '../components/questionnaire/InvitationsTab';
import ResponsesTab from '../components/questionnaire/ResponsesTab';
```

Find where the contexte/biographie fields are rendered in the creation form (around line 380-630). Wrap that block so it only shows when `form.type !== 'questionnaire'`. Then add an else branch for the questionnaire builder.

The pattern should be:

```jsx
{form.type === 'questionnaire' ? (
  <div className="text-sm text-gray-500 italic mt-4">
    {/* Builder is shown after agent creation — need to save first */}
    Créez d'abord l'agent, puis configurez les questions.
  </div>
) : (
  /* existing contexte, biographie, documents, etc. fields */
)}
```

- [ ] **Step 4: Add `welcome_message` and `closing_message` to the FormData sent on creation**

Around line 636-655, in the form submission logic, add:

```jsx
if (form.type === 'questionnaire') {
  formData.append('welcome_message', form.welcome_message || '');
  formData.append('closing_message', form.closing_message || '');
}
```

- [ ] **Step 5: Add questionnaire tabs to AgentCard or agent detail view**

In the agent list, when an agent has `type === 'questionnaire'`, the "Edit" button should navigate to a page where the user can manage questions, invitations, and responses. Since agents.js uses `router.push('/?agentId=${agent.id}')` for editing (which goes to the main index.js page), the questionnaire management will need to be integrated there.

For now, add a visual indicator on AgentCard for questionnaire agents — add a badge or icon. In the AgentCard component, detect `agent.type === 'questionnaire'` and show a `ClipboardList` icon instead of the standard Bot icon.

- [ ] **Step 6: Add questionnaire type translations to agents i18n files**

In `frontend/public/locales/fr/agents.json`, add inside the `types` object:

```json
"questionnaire": {
  "name": "Questionnaire",
  "description": "Collecte de données via chat conversationnel"
}
```

In `frontend/public/locales/en/agents.json`, add inside the `types` object:

```json
"questionnaire": {
  "name": "Questionnaire",
  "description": "Data collection via conversational chat"
}
```

- [ ] **Step 7: Commit**

```bash
git add frontend/pages/agents.js frontend/public/locales/fr/agents.json frontend/public/locales/en/agents.json
git commit -m "feat(ui): integrate questionnaire type into agents page"
```

---

## Task 17: Frontend — Public questionnaire page

**Files:**
- Create: `frontend/pages/questionnaire/[token].js`

- [ ] **Step 1: Create the public questionnaire page**

Create `frontend/pages/questionnaire/[token].js`:

```jsx
import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/router';
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import { Bot, Send, Star, CheckCircle } from 'lucide-react';
import axios from 'axios';

const API_URL = '/_api';

export default function PublicQuestionnaire() {
  const { t } = useTranslation('questionnaire');
  const router = useRouter();
  const { token } = router.query;
  const messagesEndRef = useRef(null);

  const [questionnaire, setQuestionnaire] = useState(null);
  const [messages, setMessages] = useState([]);
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [inputValue, setInputValue] = useState('');
  const [selectedChoices, setSelectedChoices] = useState([]);
  const [selectedRating, setSelectedRating] = useState(0);
  const [isCompleted, setIsCompleted] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (token) loadQuestionnaire();
  }, [token]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const loadQuestionnaire = async () => {
    try {
      const res = await axios.get(`${API_URL}/questionnaire/${token}`);
      if (res.data.status === 'completed') {
        setIsCompleted(true);
        setIsLoading(false);
        return;
      }
      setQuestionnaire(res.data);

      // Filter out already-answered questions
      const answeredIds = new Set(res.data.answered_question_ids || []);
      const unanswered = res.data.questions.filter(q => !answeredIds.has(q.id));

      if (unanswered.length === 0) {
        setIsCompleted(true);
        setIsLoading(false);
        return;
      }

      // Replace questions with only unanswered ones
      res.data.questions = unanswered;
      setQuestionnaire(res.data);

      // Welcome message
      const welcomeMsg = res.data.welcome_message
        ? `Bonjour${res.data.respondent_name ? ` ${res.data.respondent_name}` : ''} ! ${res.data.welcome_message}`
        : `Bonjour${res.data.respondent_name ? ` ${res.data.respondent_name}` : ''} ! Merci de prendre le temps de répondre à ce questionnaire.`;
      setMessages([{ role: 'agent', content: welcomeMsg }]);

      // Show first question after a brief delay
      setTimeout(() => {
        setMessages(prev => [...prev, { role: 'agent', content: unanswered[0].question_text, questionIndex: 0 }]);
        setIsLoading(false);
      }, 800);
    } catch (err) {
      if (err.response?.status === 404) {
        setError(t('public.notFound'));
      } else if (err.response?.data?.status === 'completed') {
        setIsCompleted(true);
      }
      setIsLoading(false);
    }
  };

  const currentQuestion = questionnaire?.questions?.[currentQuestionIndex];

  const submitAnswer = async (answerText) => {
    if (!currentQuestion || isSending) return;
    setIsSending(true);

    // Add user message
    setMessages(prev => [...prev, { role: 'user', content: answerText }]);

    try {
      await axios.post(`${API_URL}/questionnaire/${token}/answer`, {
        question_id: currentQuestion.id,
        answer_text: answerText,
      });

      const nextIndex = currentQuestionIndex + 1;
      if (nextIndex < questionnaire.questions.length) {
        setCurrentQuestionIndex(nextIndex);
        setInputValue('');
        setSelectedChoices([]);
        setSelectedRating(0);
        // Show next question
        setTimeout(() => {
          setMessages(prev => [...prev, {
            role: 'agent',
            content: questionnaire.questions[nextIndex].question_text,
            questionIndex: nextIndex,
          }]);
        }, 500);
      } else {
        // Complete
        try {
          const res = await axios.post(`${API_URL}/questionnaire/${token}/complete`);
          setMessages(prev => [...prev, { role: 'agent', content: res.data.closing_message || 'Merci pour vos réponses !' }]);
        } catch {
          setMessages(prev => [...prev, { role: 'agent', content: 'Merci pour vos réponses !' }]);
        }
        setIsCompleted(true);
      }
    } catch (err) {
      console.error('Failed to submit answer:', err);
    } finally {
      setIsSending(false);
    }
  };

  const handleTextSubmit = () => {
    if (!inputValue.trim()) return;
    submitAnswer(inputValue.trim());
  };

  const handleSingleChoice = (option) => {
    submitAnswer(option);
  };

  const handleMultipleChoiceConfirm = () => {
    if (selectedChoices.length === 0) return;
    submitAnswer(selectedChoices.join(', '));
  };

  const handleRatingSubmit = () => {
    if (selectedRating === 0) return;
    submitAnswer(String(selectedRating));
  };

  const toggleChoice = (option) => {
    setSelectedChoices(prev =>
      prev.includes(option) ? prev.filter(c => c !== option) : [...prev, option]
    );
  };

  // Parse options for current question
  const parsedOptions = (() => {
    if (!currentQuestion?.options) return [];
    try { return JSON.parse(currentQuestion.options); } catch { return []; }
  })();

  const ratingConfig = (() => {
    if (currentQuestion?.question_type !== 'rating') return { min: 1, max: 5 };
    try { return JSON.parse(currentQuestion?.options || '{}'); } catch { return { min: 1, max: 5 }; }
  })();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <p className="text-gray-500">{error}</p>
      </div>
    );
  }

  if (isCompleted && messages.length === 0) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <CheckCircle className="w-16 h-16 text-green-500 mx-auto mb-4" />
          <p className="text-gray-600 text-lg">{t('public.completed')}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-3 shadow-sm">
        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-primary-500 to-purple-500 flex items-center justify-center">
          <Bot className="w-5 h-5 text-white" />
        </div>
        <div>
          <h1 className="font-heading font-bold text-gray-900">{questionnaire?.agent_name || 'Questionnaire'}</h1>
          <p className="text-xs text-gray-500">TAIC Companion</p>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6 max-w-2xl mx-auto w-full">
        <div className="space-y-4">
          {messages.map((msg, idx) => (
            <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} items-end gap-2 animate-fade-in`}>
              {msg.role === 'agent' && (
                <div className="w-7 h-7 rounded-sm bg-primary-50 flex items-center justify-center shrink-0 mb-1">
                  <Bot className="w-3.5 h-3.5 text-primary-600" />
                </div>
              )}
              <div className={`rounded-2xl px-5 py-3.5 max-w-[75%] shadow-sm ${
                msg.role === 'user'
                  ? 'bg-gradient-to-br from-primary-600 to-primary-700 text-white rounded-br-none'
                  : 'bg-white text-gray-900 rounded-bl-none border border-gray-200'
              }`}>
                <p className="leading-relaxed whitespace-pre-line text-sm">{msg.content}</p>
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input area */}
      {!isCompleted && currentQuestion && (
        <div className="border-t border-gray-200 bg-white px-4 py-4">
          <div className="max-w-2xl mx-auto">
            {/* Open question */}
            {currentQuestion.question_type === 'open' && (
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleTextSubmit()}
                  placeholder={t('public.inputPlaceholder')}
                  className="flex-1 px-4 py-3 border border-gray-200 rounded-full text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                  disabled={isSending}
                />
                <button
                  onClick={handleTextSubmit}
                  disabled={!inputValue.trim() || isSending}
                  className="p-3 bg-primary-600 text-white rounded-full hover:bg-primary-700 disabled:opacity-50 transition-colors"
                >
                  <Send className="w-4 h-4" />
                </button>
              </div>
            )}

            {/* Single choice */}
            {currentQuestion.question_type === 'single_choice' && (
              <div className="flex flex-wrap gap-2 justify-center">
                {parsedOptions.map((opt, idx) => (
                  <button
                    key={idx}
                    onClick={() => handleSingleChoice(opt)}
                    disabled={isSending}
                    className="px-5 py-2.5 border border-gray-200 rounded-full text-sm font-medium text-gray-700 hover:bg-primary-50 hover:border-primary-300 hover:text-primary-700 transition-colors disabled:opacity-50"
                  >
                    {opt}
                  </button>
                ))}
              </div>
            )}

            {/* Multiple choice */}
            {currentQuestion.question_type === 'multiple_choice' && (
              <div className="space-y-3">
                <div className="flex flex-wrap gap-2 justify-center">
                  {parsedOptions.map((opt, idx) => (
                    <button
                      key={idx}
                      onClick={() => toggleChoice(opt)}
                      disabled={isSending}
                      className={`px-5 py-2.5 border rounded-full text-sm font-medium transition-colors ${
                        selectedChoices.includes(opt)
                          ? 'bg-primary-600 text-white border-primary-600'
                          : 'border-gray-200 text-gray-700 hover:bg-primary-50 hover:border-primary-300'
                      }`}
                    >
                      {opt}
                    </button>
                  ))}
                </div>
                <div className="text-center">
                  <button
                    onClick={handleMultipleChoiceConfirm}
                    disabled={selectedChoices.length === 0 || isSending}
                    className="px-6 py-2.5 bg-primary-600 text-white rounded-full text-sm font-medium hover:bg-primary-700 disabled:opacity-50 transition-colors"
                  >
                    {t('public.validateChoices')} ({selectedChoices.length})
                  </button>
                </div>
              </div>
            )}

            {/* Rating */}
            {currentQuestion.question_type === 'rating' && (
              <div className="space-y-3">
                <div className="flex justify-center gap-2">
                  {Array.from({ length: (ratingConfig.max || 5) - (ratingConfig.min || 1) + 1 }, (_, i) => {
                    const value = (ratingConfig.min || 1) + i;
                    return (
                      <button
                        key={value}
                        onClick={() => setSelectedRating(value)}
                        disabled={isSending}
                        className="p-1 transition-transform hover:scale-110"
                      >
                        <Star className={`w-8 h-8 ${value <= selectedRating ? 'text-yellow-400 fill-yellow-400' : 'text-gray-300'}`} />
                      </button>
                    );
                  })}
                </div>
                {selectedRating > 0 && (
                  <div className="text-center">
                    <button
                      onClick={handleRatingSubmit}
                      disabled={isSending}
                      className="px-6 py-2.5 bg-primary-600 text-white rounded-full text-sm font-medium hover:bg-primary-700 disabled:opacity-50 transition-colors"
                    >
                      {t('public.nextButton')}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export async function getServerSideProps({ locale }) {
  return {
    props: {
      ...(await serverSideTranslations(locale, ['questionnaire', 'common'])),
    },
  };
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/pages/questionnaire/[token].js
git commit -m "feat(ui): add public questionnaire page with conversational chat interface"
```

---

## Task 18: Backend — Handle welcome_message and closing_message in agent creation

**Files:**
- Modify: `backend/routers/agents.py`

- [ ] **Step 1: Handle the new fields in agent creation endpoint**

In `backend/routers/agents.py`, find the agent creation endpoint (the `POST /api/agents` or the form handling section that creates an Agent object). After the existing field assignments (around where `type` and `enabled_plugins` are set), add:

```python
# Questionnaire fields
if agent_type == "questionnaire":
    agent.welcome_message = form_data.get("welcome_message", "")
    agent.closing_message = form_data.get("closing_message", "")
    agent.llm_provider = "mistral"
```

Also find the PATCH/update endpoint and add the same fields to the update logic.

- [ ] **Step 2: Commit**

```bash
git add backend/routers/agents.py
git commit -m "feat(api): handle questionnaire welcome/closing message in agent CRUD"
```

---

## Task 19: Install weasyprint dependency

**Files:**
- Modify: `backend/requirements.txt` (or `Dockerfile` / `pyproject.toml` depending on setup)

- [ ] **Step 1: Check which dependency file exists and add weasyprint**

Check for `backend/requirements.txt` or `backend/pyproject.toml`. Add `weasyprint` to the dependencies list.

For `requirements.txt`:
```
weasyprint>=60.0
```

Note: weasyprint has system-level dependencies (pango, cairo). For the Docker build, these may need to be added to the Dockerfile. Check the existing Dockerfile for the backend and add:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 \
    && rm -rf /var/lib/apt/lists/*
```

If weasyprint proves too complex to install, the PDF endpoint already has a fallback to return HTML.

- [ ] **Step 2: Commit**

```bash
git add backend/requirements.txt  # or the relevant file
git commit -m "chore(deps): add weasyprint for PDF generation"
```

---

## Task 20: Integration test — End-to-end flow verification

**Files:** No new files — manual verification

- [ ] **Step 1: Start the backend and verify the new tables are created**

```bash
cd backend && python -m uvicorn main:app --reload --port 8080
```

Check logs for:
- `ensure_columns: agents.welcome_message OK`
- `ensure_columns: agents.closing_message OK`
- No errors related to `questionnaire_questions`, `questionnaire_responses`, or `questionnaire_answers` table creation

- [ ] **Step 2: Test agent creation with type=questionnaire via API**

```bash
# Create a questionnaire agent (adjust auth token)
curl -X POST http://localhost:8080/api/agents \
  -H "Authorization: Bearer <token>" \
  -F "name=Test Questionnaire" \
  -F "type=questionnaire" \
  -F "welcome_message=Enquête de satisfaction" \
  -F "closing_message=Merci !"
```

- [ ] **Step 3: Test question CRUD**

```bash
# Add a question
curl -X POST http://localhost:8080/api/agents/<id>/questions \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"question_text":"Comment évaluez-vous notre service ?","question_type":"rating","options":"{\"min\":1,\"max\":5}"}'

# List questions
curl http://localhost:8080/api/agents/<id>/questions -H "Authorization: Bearer <token>"
```

- [ ] **Step 4: Test invitation**

```bash
curl -X POST http://localhost:8080/api/agents/<id>/invite \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"emails":["test@example.com"],"names":["Jean Test"]}'
```

- [ ] **Step 5: Test public questionnaire flow**

```bash
# Get questionnaire
curl http://localhost:8080/questionnaire/<token>

# Submit answer
curl -X POST http://localhost:8080/questionnaire/<token>/answer \
  -H "Content-Type: application/json" \
  -d '{"question_id":1,"answer_text":"4"}'

# Complete
curl -X POST http://localhost:8080/questionnaire/<token>/complete
```

- [ ] **Step 6: Start frontend and verify UI**

```bash
cd frontend && npm run dev
```

Verify:
- Agent creation form shows "Questionnaire" in type selector
- Selecting questionnaire hides RAG/contexte fields
- Public page at `/questionnaire/<token>` loads and shows conversational chat

- [ ] **Step 7: Final commit with any fixes**

```bash
git add -A
git commit -m "fix: integration adjustments for questionnaire companion"
```
