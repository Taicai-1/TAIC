# Multi-Recap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow multiple independent recaps per agent, each with its own configuration (name, frequency, hour, prompt, recipients) and document associations.

**Architecture:** New `Recap` model with 1:N relationship to Agent, and `RecapDocument` join table for document inclusion/exclusion. The scheduler iterates over Recaps instead of Agents. Email ingest auto-associates new documents to all existing recaps. Frontend replaces the single recap form with a list of recap cards, each expandable to show settings and document toggles.

**Tech Stack:** SQLAlchemy (database models), FastAPI (REST endpoints), Next.js/React (frontend), PostgreSQL (storage with RLS)

---

## File Structure

### New Files
- `backend/routers/recaps.py` - All recap CRUD and action endpoints (create, read, update, delete, document management, preview, send)

### Modified Files
- `backend/database.py` - Add `Recap`, `RecapDocument` models; add `recap_id` to `WeeklyRecapLog`
- `backend/weekly_recap.py` - Add `process_recap()` function alongside existing `process_agent_recap()`
- `backend/recap_scheduler.py` - Change scheduler to iterate over Recaps instead of Agents
- `backend/routers/email_ingest.py` - After creating traceability doc, create `RecapDocument` entries for all agent recaps
- `backend/routers/agents.py` - Keep old recap endpoints as compat shims
- `backend/main.py` - Register the new `recaps` router
- `backend/email_service.py` - Update `send_recap_email` to accept recap name for email subject
- `frontend/pages/index.js` - Replace single recap form with multi-recap UI (list, create, edit, document toggles)

---

### Task 1: Add Recap and RecapDocument models to database.py

**Files:**
- Modify: `backend/database.py:483-497` (after WeeklyRecapLog, before RoutineReport)
- Modify: `backend/database.py:618-668` (ensure_columns migrations)
- Modify: `backend/database.py:691-700` (ensure_rls_policies tables list)

- [ ] **Step 1: Add the Recap model after WeeklyRecapLog class**

In `backend/database.py`, add after the `WeeklyRecapLog` class (line 497) and before `RoutineReport`:

```python
class Recap(Base):
    __tablename__ = "recaps"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    frequency = Column(String(20), default="weekly", nullable=False)
    hour = Column(Integer, default=9, nullable=False)
    prompt = Column(Text, nullable=True)
    recipients = Column(Text, nullable=True)  # JSON array of email addresses
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    agent = relationship("Agent")
    recap_documents = relationship("RecapDocument", back_populates="recap", cascade="all, delete-orphan")


class RecapDocument(Base):
    __tablename__ = "recap_documents"
    __table_args__ = (UniqueConstraint("recap_id", "document_id", name="uq_recap_document"),)

    id = Column(Integer, primary_key=True, index=True)
    recap_id = Column(Integer, ForeignKey("recaps.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    included = Column(Boolean, default=True, nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)

    recap = relationship("Recap", back_populates="recap_documents")
    document = relationship("Document")
```

- [ ] **Step 2: Add recap_id to WeeklyRecapLog**

In `backend/database.py`, add to the `WeeklyRecapLog` class (around line 489), after `agent_id`:

```python
recap_id = Column(Integer, ForeignKey("recaps.id"), nullable=True, index=True)
```

And add a relationship:
```python
recap = relationship("Recap")
```

- [ ] **Step 3: Add migration entries in ensure_columns()**

In `backend/database.py`, inside the `ensure_columns()` function's `migrations` list (around line 620), add:

```python
("weekly_recap_logs", "recap_id", "INTEGER REFERENCES recaps(id)"),
```

Note: The `recaps` and `recap_documents` tables will be created by `Base.metadata.create_all()` in `init_db()`. No manual ALTER TABLE needed for them.

- [ ] **Step 4: Add new tables to RLS policies**

In `backend/database.py`, in the `ensure_rls_policies()` function, add `"recaps"` and `"recap_documents"` to the `tables` list (around line 691):

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
]
```

- [ ] **Step 5: Add Recap and RecapDocument to database imports used elsewhere**

In `backend/database.py`, no import changes needed since models are defined in the same file. But verify the new models are importable:

```bash
cd backend && python -c "from database import Recap, RecapDocument; print('OK')"
```

- [ ] **Step 6: Commit**

```bash
git add backend/database.py
git commit -m "feat: add Recap and RecapDocument models for multi-recap support"
```

---

### Task 2: Create recap CRUD endpoints (backend/routers/recaps.py)

**Files:**
- Create: `backend/routers/recaps.py`
- Modify: `backend/main.py` (register router)

- [ ] **Step 1: Create the recaps router file**

Create `backend/routers/recaps.py`:

```python
"""Recap CRUD and action endpoints."""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import verify_token
from database import get_db, Agent, Document, Recap, RecapDocument, WeeklyRecapLog, User
from helpers.tenant import _get_caller_company_id

logger = logging.getLogger(__name__)
router = APIRouter()


class RecapCreate(BaseModel):
    name: str
    enabled: bool = True
    frequency: str = "weekly"
    hour: int = 9
    prompt: str | None = None
    recipients: list[str] | None = None


class RecapUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    frequency: str | None = None
    hour: int | None = None
    prompt: str | None = None
    recipients: list[str] | None = None


class RecapDocumentUpdate(BaseModel):
    included: bool


def _get_agent_for_user(agent_id: int, user_id: int, db: Session) -> Agent:
    agent = db.query(Agent).filter(Agent.id == agent_id, Agent.user_id == user_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def _get_recap_for_user(recap_id: int, user_id: int, db: Session) -> Recap:
    recap = db.query(Recap).filter(Recap.id == recap_id).first()
    if not recap:
        raise HTTPException(status_code=404, detail="Recap not found")
    agent = db.query(Agent).filter(Agent.id == recap.agent_id, Agent.user_id == user_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Recap not found")
    return recap


def _recap_to_dict(recap: Recap) -> dict:
    recipients = []
    if recap.recipients:
        try:
            recipients = json.loads(recap.recipients)
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "id": recap.id,
        "agent_id": recap.agent_id,
        "name": recap.name,
        "enabled": recap.enabled,
        "frequency": recap.frequency,
        "hour": recap.hour,
        "prompt": recap.prompt,
        "recipients": recipients,
        "created_at": recap.created_at.isoformat() if recap.created_at else None,
        "updated_at": recap.updated_at.isoformat() if recap.updated_at else None,
        "document_count": len([rd for rd in recap.recap_documents if rd.included]),
    }


@router.get("/api/agents/{agent_id}/recaps")
async def list_recaps(agent_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    agent = _get_agent_for_user(agent_id, int(user_id), db)
    recaps = db.query(Recap).filter(Recap.agent_id == agent.id).order_by(Recap.created_at.asc()).all()
    return {"recaps": [_recap_to_dict(r) for r in recaps]}


@router.post("/api/agents/{agent_id}/recaps")
async def create_recap(
    agent_id: int, body: RecapCreate, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    agent = _get_agent_for_user(agent_id, int(user_id), db)
    caller_company_id = _get_caller_company_id(user_id, db)

    if body.frequency not in ("daily", "weekly", "monthly"):
        raise HTTPException(status_code=400, detail="frequency must be daily, weekly, or monthly")
    if not (0 <= body.hour <= 23):
        raise HTTPException(status_code=400, detail="hour must be between 0 and 23")

    recap = Recap(
        agent_id=agent.id,
        company_id=caller_company_id,
        name=body.name,
        enabled=body.enabled,
        frequency=body.frequency,
        hour=body.hour,
        prompt=body.prompt if body.prompt and body.prompt.strip() else None,
        recipients=json.dumps(body.recipients) if body.recipients else None,
    )
    db.add(recap)
    db.commit()
    db.refresh(recap)

    # Associate all existing traceability documents with this recap
    trace_docs = (
        db.query(Document)
        .filter(Document.agent_id == agent.id, Document.document_type == "traceability")
        .all()
    )
    for doc in trace_docs:
        rd = RecapDocument(
            recap_id=recap.id,
            document_id=doc.id,
            included=True,
            company_id=caller_company_id,
        )
        db.add(rd)
    db.commit()
    db.refresh(recap)

    return {"recap": _recap_to_dict(recap)}


@router.put("/api/agents/{agent_id}/recaps/{recap_id}")
async def update_recap(
    agent_id: int, recap_id: int, body: RecapUpdate, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    _get_agent_for_user(agent_id, int(user_id), db)
    recap = _get_recap_for_user(recap_id, int(user_id), db)

    if body.name is not None:
        recap.name = body.name
    if body.enabled is not None:
        recap.enabled = body.enabled
    if body.frequency is not None:
        if body.frequency not in ("daily", "weekly", "monthly"):
            raise HTTPException(status_code=400, detail="frequency must be daily, weekly, or monthly")
        recap.frequency = body.frequency
    if body.hour is not None:
        if not (0 <= body.hour <= 23):
            raise HTTPException(status_code=400, detail="hour must be between 0 and 23")
        recap.hour = body.hour
    if body.prompt is not None:
        recap.prompt = body.prompt if body.prompt.strip() else None
    if body.recipients is not None:
        recap.recipients = json.dumps(body.recipients) if body.recipients else None

    recap.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(recap)

    return {"recap": _recap_to_dict(recap)}


@router.delete("/api/agents/{agent_id}/recaps/{recap_id}")
async def delete_recap(
    agent_id: int, recap_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    _get_agent_for_user(agent_id, int(user_id), db)
    recap = _get_recap_for_user(recap_id, int(user_id), db)
    db.delete(recap)
    db.commit()
    return {"message": "Recap deleted"}


@router.get("/api/recaps/{recap_id}/documents")
async def list_recap_documents(
    recap_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    recap = _get_recap_for_user(recap_id, int(user_id), db)
    # Get all traceability docs for the agent and their recap_document status
    agent_docs = (
        db.query(Document)
        .filter(Document.agent_id == recap.agent_id, Document.document_type == "traceability")
        .order_by(Document.created_at.desc())
        .all()
    )

    # Build a map of document_id -> RecapDocument for this recap
    rd_map = {}
    for rd in recap.recap_documents:
        rd_map[rd.document_id] = rd

    result = []
    for doc in agent_docs:
        rd = rd_map.get(doc.id)
        result.append({
            "document_id": doc.id,
            "filename": doc.filename,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "included": rd.included if rd else True,
            "recap_document_id": rd.id if rd else None,
        })

    return {"documents": result}


@router.put("/api/recaps/{recap_id}/documents/{document_id}")
async def update_recap_document(
    recap_id: int,
    document_id: int,
    body: RecapDocumentUpdate,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    recap = _get_recap_for_user(recap_id, int(user_id), db)
    caller_company_id = _get_caller_company_id(user_id, db)

    rd = (
        db.query(RecapDocument)
        .filter(RecapDocument.recap_id == recap.id, RecapDocument.document_id == document_id)
        .first()
    )

    if rd:
        rd.included = body.included
    else:
        # Create the association if it doesn't exist
        rd = RecapDocument(
            recap_id=recap.id,
            document_id=document_id,
            included=body.included,
            company_id=caller_company_id,
        )
        db.add(rd)

    db.commit()
    return {"included": body.included}


@router.post("/api/recaps/{recap_id}/preview")
async def recap_preview(recap_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    recap = _get_recap_for_user(recap_id, int(user_id), db)
    agent = db.query(Agent).filter(Agent.id == recap.agent_id).first()

    from weekly_recap import (
        fetch_weekly_messages,
        fetch_recap_traceability_documents,
        fetch_notion_content,
        build_recap_prompt,
        get_model_id_for_agent,
        FREQUENCY_DAYS,
    )
    from email_service import generate_recap_html
    from openai_client import get_chat_response as _get_chat_response

    days_back = FREQUENCY_DAYS.get(recap.frequency, 7)
    messages = fetch_weekly_messages(agent.id, db, days_back=days_back)
    docs = fetch_recap_traceability_documents(recap.id, db, days_back=days_back)
    notion_pages = fetch_notion_content(agent.id, db)

    if not messages and not docs and not notion_pages:
        return {"status": "no_data", "message": "No data for this period", "html": None}

    prompt_messages = build_recap_prompt(
        agent, messages, docs, notion_pages, frequency=recap.frequency, custom_prompt=recap.prompt
    )
    model_id = get_model_id_for_agent(agent)
    recap_content = _get_chat_response(prompt_messages, model_id=model_id)
    html = generate_recap_html(agent.name, recap_content, recap_name=recap.name)

    return {
        "status": "success",
        "html": html,
        "message_count": len(messages),
        "doc_count": len(docs),
        "notion_count": len(notion_pages),
    }


@router.post("/api/recaps/{recap_id}/send")
async def recap_send(recap_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    recap = _get_recap_for_user(recap_id, int(user_id), db)
    if not recap.enabled:
        raise HTTPException(status_code=400, detail="Recap is not enabled")

    from weekly_recap import process_recap

    result = process_recap(recap, db)
    return result
```

- [ ] **Step 2: Register the recaps router in main.py**

In `backend/main.py`, find where other routers are included (search for `app.include_router`), and add:

```python
from routers.recaps import router as recaps_router
app.include_router(recaps_router)
```

- [ ] **Step 3: Verify the router loads**

```bash
cd backend && python -c "from routers.recaps import router; print('Router loaded, routes:', len(router.routes))"
```

- [ ] **Step 4: Commit**

```bash
git add backend/routers/recaps.py backend/main.py
git commit -m "feat: add recap CRUD and action endpoints"
```

---

### Task 3: Update weekly_recap.py with process_recap() and fetch_recap_traceability_documents()

**Files:**
- Modify: `backend/weekly_recap.py`

- [ ] **Step 1: Add fetch_recap_traceability_documents function**

In `backend/weekly_recap.py`, after the existing `fetch_traceability_documents` function (line 69), add:

```python
def fetch_recap_traceability_documents(recap_id: int, db: Session, days_back: int = 7) -> list[dict]:
    """Fetch traceability documents for a specific recap, filtered by RecapDocument inclusion."""
    from database import RecapDocument
    cutoff = datetime.utcnow() - timedelta(days=days_back)
    docs = (
        db.query(Document)
        .join(RecapDocument, RecapDocument.document_id == Document.id)
        .filter(
            RecapDocument.recap_id == recap_id,
            RecapDocument.included == True,
            Document.document_type == "traceability",
            Document.created_at >= cutoff,
        )
        .all()
    )
    return [{"filename": d.filename, "content": (d.content or "")[:10000]} for d in docs]
```

- [ ] **Step 2: Update build_recap_prompt to accept an optional custom_prompt parameter**

In `backend/weekly_recap.py`, modify the `build_recap_prompt` function signature (line 122) to add `custom_prompt`:

Change:
```python
def build_recap_prompt(
    agent: Agent,
    messages: list[dict],
    docs: list[dict],
    notion_pages: list[dict] | None = None,
    frequency: str = "weekly",
) -> list[dict]:
```

To:
```python
def build_recap_prompt(
    agent: Agent,
    messages: list[dict],
    docs: list[dict],
    notion_pages: list[dict] | None = None,
    frequency: str = "weekly",
    custom_prompt: str | None = None,
) -> list[dict]:
```

Then update line 151 to use `custom_prompt` parameter first, falling back to agent attribute:

Change:
```python
    custom_prompt = getattr(agent, "weekly_recap_prompt", None)
```

To:
```python
    custom_prompt = custom_prompt or getattr(agent, "weekly_recap_prompt", None)
```

- [ ] **Step 3: Add the process_recap function**

In `backend/weekly_recap.py`, after the existing `process_agent_recap` function (line 293), add:

```python
def process_recap(recap, db: Session) -> dict:
    """Full pipeline for a single Recap entity: fetch data -> LLM -> email -> log."""
    from database import Recap, User, WeeklyRecapLog
    agent = db.query(Agent).filter(Agent.id == recap.agent_id).first()
    if not agent:
        return {"status": "error", "error": "Agent not found"}

    user = db.query(User).filter(User.id == agent.user_id).first()
    if not user:
        return {"status": "error", "error": "User not found"}

    try:
        days_back = FREQUENCY_DAYS.get(recap.frequency, 7)
        messages = fetch_weekly_messages(agent.id, db, days_back=days_back)
        docs = fetch_recap_traceability_documents(recap.id, db, days_back=days_back)
        notion_pages = fetch_notion_content(agent.id, db)

        if not messages and not docs and not notion_pages:
            log = WeeklyRecapLog(
                agent_id=agent.id,
                recap_id=recap.id,
                user_id=user.id,
                company_id=agent.company_id,
                status="no_data",
                recap_content=None,
            )
            db.add(log)
            db.commit()
            return {"status": "no_data", "message": "No data for this period"}

        prompt_messages = build_recap_prompt(
            agent, messages, docs, notion_pages,
            frequency=recap.frequency, custom_prompt=recap.prompt,
        )
        model_id = get_model_id_for_agent(agent)
        recap_content = get_chat_response(prompt_messages, model_id=model_id)

        html = generate_recap_html(agent.name, recap_content, recap_name=recap.name)

        # Build recipient list
        recipients = [user.email]
        if recap.recipients:
            try:
                import json
                extra = json.loads(recap.recipients)
                if isinstance(extra, list):
                    recipients.extend(e.strip() for e in extra if e.strip() and e.strip() != user.email)
            except (json.JSONDecodeError, TypeError):
                pass
        seen = set()
        unique_recipients = []
        for r in recipients:
            if r not in seen:
                seen.add(r)
                unique_recipients.append(r)

        send_recap_email(unique_recipients, agent.name, html, recap_name=recap.name)

        log = WeeklyRecapLog(
            agent_id=agent.id,
            recap_id=recap.id,
            user_id=user.id,
            company_id=agent.company_id,
            status="success",
            recap_content=recap_content,
        )
        db.add(log)
        db.commit()

        return {
            "status": "success",
            "agent_name": agent.name,
            "recap_name": recap.name,
            "email": ", ".join(unique_recipients),
            "message_count": len(messages),
            "doc_count": len(docs),
        }

    except Exception as e:
        logger.error(f"Recap failed for recap {recap.id}: {e}")
        try:
            log = WeeklyRecapLog(
                agent_id=agent.id,
                recap_id=recap.id,
                user_id=user.id,
                company_id=agent.company_id,
                status="error",
                error_message=str(e)[:500],
            )
            db.add(log)
            db.commit()
        except Exception:
            db.rollback()
        return {"status": "error", "error": str(e)}
```

- [ ] **Step 4: Commit**

```bash
git add backend/weekly_recap.py
git commit -m "feat: add process_recap and fetch_recap_traceability_documents"
```

---

### Task 4: Update email_service.py to support recap name in subject

**Files:**
- Modify: `backend/email_service.py:216-239`

- [ ] **Step 1: Update generate_recap_html to accept recap_name**

In `backend/email_service.py`, change line 216:

```python
def generate_recap_html(agent_name: str, recap_content: str) -> str:
```

To:

```python
def generate_recap_html(agent_name: str, recap_content: str, recap_name: str | None = None) -> str:
```

Then update the header line inside the function (line 222-224). Change:

```python
    content = f"""
<p style="color:#6b7280; font-size:14px; margin:0 0 20px 0; text-align:center;">
  {agent_name} &mdash; Semaine du {now}
</p>
```

To:

```python
    display_name = f"{recap_name} - {agent_name}" if recap_name else agent_name
    content = f"""
<p style="color:#6b7280; font-size:14px; margin:0 0 20px 0; text-align:center;">
  {display_name} &mdash; Semaine du {now}
</p>
```

Also update the preheader at line 231:

```python
    return _wrap_template(content, preheader=f"Recap - {display_name}")
```

- [ ] **Step 2: Update send_recap_email to accept recap_name**

In `backend/email_service.py`, change line 234:

```python
def send_recap_email(to_email: str | list[str], agent_name: str, html: str):
```

To:

```python
def send_recap_email(to_email: str | list[str], agent_name: str, html: str, recap_name: str | None = None):
```

Then update the subject line (line 236):

```python
    subject = f"Recap {recap_name} - {agent_name}" if recap_name else f"Recap Hebdomadaire - {agent_name}"
```

- [ ] **Step 3: Commit**

```bash
git add backend/email_service.py
git commit -m "feat: include recap name in email subject and header"
```

---

### Task 5: Update recap_scheduler.py to iterate over Recaps

**Files:**
- Modify: `backend/recap_scheduler.py`

- [ ] **Step 1: Update imports**

In `backend/recap_scheduler.py`, change line 15:

```python
from database import SessionLocal, Agent, WeeklyRecapLog
```

To:

```python
from database import SessionLocal, Agent, Recap, WeeklyRecapLog
```

- [ ] **Step 2: Add _is_recap_due function**

In `backend/recap_scheduler.py`, after the existing `_is_due` function (line 58), add:

```python
def _is_recap_due(recap: Recap, now: datetime, db) -> bool:
    """Check if a Recap entity is due for sending right now."""
    freq = recap.frequency or "weekly"
    hour = recap.hour if recap.hour is not None else 9
    current_hour = now.hour

    if freq in ("daily", "weekly", "monthly"):
        if current_hour != hour:
            return False
    else:
        return False

    if freq == "weekly" and now.weekday() != 0:
        return False

    if freq == "monthly" and now.day != 1:
        return False

    last_log = (
        db.query(WeeklyRecapLog)
        .filter(
            WeeklyRecapLog.recap_id == recap.id,
            WeeklyRecapLog.status.in_(["success", "no_data"]),
        )
        .order_by(WeeklyRecapLog.sent_at.desc())
        .first()
    )

    if last_log and last_log.sent_at:
        min_gap = {"daily": timedelta(hours=23), "weekly": timedelta(days=6), "monthly": timedelta(days=27)}
        if now.replace(tzinfo=None) - last_log.sent_at < min_gap.get(freq, timedelta(days=6)):
            return False

    return True
```

- [ ] **Step 3: Update _run_scheduled_recaps to iterate Recaps**

In `backend/recap_scheduler.py`, replace the `_run_scheduled_recaps` function (lines 61-88) with:

```python
def _run_scheduled_recaps():
    """Hourly tick: find and process all due recaps (both legacy agent-level and new Recap entities)."""
    logger.info("Recap scheduler tick starting")
    now = datetime.now(PARIS_TZ)
    db = SessionLocal()

    try:
        db.execute(text("SET LOCAL app.service_bypass = 'true'"))

        # Process new Recap entities
        recaps = db.query(Recap).filter(Recap.enabled == True).all()
        recap_due_count = 0

        for recap in recaps:
            if _is_recap_due(recap, now, db):
                recap_due_count += 1
                try:
                    from weekly_recap import process_recap
                    result = process_recap(recap, db)
                    logger.info(f"Recap {recap.id} ({recap.name}): {result.get('status')}")
                except Exception as e:
                    logger.error(f"Recap failed for recap {recap.id}: {e}")

        # Legacy: still process agents with weekly_recap_enabled that have NO Recap entities
        agents = db.query(Agent).filter(Agent.weekly_recap_enabled == True).all()
        legacy_due_count = 0
        for agent in agents:
            has_recaps = db.query(Recap).filter(Recap.agent_id == agent.id).count() > 0
            if has_recaps:
                continue  # Skip — handled by Recap entities above
            if _is_due(agent, now, db):
                legacy_due_count += 1
                try:
                    from weekly_recap import process_agent_recap
                    result = process_agent_recap(agent, db)
                    logger.info(f"Legacy recap for agent {agent.id} ({agent.name}): {result.get('status')}")
                except Exception as e:
                    logger.error(f"Legacy recap failed for agent {agent.id}: {e}")

        logger.info(
            f"Recap scheduler tick done: {recap_due_count} recaps + {legacy_due_count} legacy agents processed"
        )
    except Exception as e:
        logger.error(f"Recap scheduler tick failed: {e}")
    finally:
        db.close()
```

- [ ] **Step 4: Commit**

```bash
git add backend/recap_scheduler.py
git commit -m "feat: scheduler iterates over Recap entities with legacy fallback"
```

---

### Task 6: Update email_ingest.py to create RecapDocument entries

**Files:**
- Modify: `backend/routers/email_ingest.py:410-422`

- [ ] **Step 1: Add RecapDocument creation after traceability doc creation**

In `backend/routers/email_ingest.py`, after the traceability document is committed (around line 422, after `db.commit()`), add:

```python
                # Associate traceability doc with all existing recaps for this agent
                from database import Recap, RecapDocument
                agent_recaps = db.query(Recap).filter(Recap.agent_id == agent.id).all()
                for recap in agent_recaps:
                    rd = RecapDocument(
                        recap_id=recap.id,
                        document_id=trace_doc.id,
                        included=True,
                        company_id=agent.company_id,
                    )
                    db.add(rd)
                if agent_recaps:
                    db.commit()
```

This goes right after the existing `db.commit()` on line 422, inside the `if not trace_exists:` block.

- [ ] **Step 2: Commit**

```bash
git add backend/routers/email_ingest.py
git commit -m "feat: auto-associate traceability docs with all agent recaps on email ingest"
```

---

### Task 7: Update agents.py recap endpoints for backwards compatibility

**Files:**
- Modify: `backend/routers/agents.py:592-679`

- [ ] **Step 1: Update trigger endpoint to also process Recap entities**

In `backend/routers/agents.py`, update the `trigger_weekly_recap` function (lines 592-623). Replace lines 605-621:

```python
    from weekly_recap import process_agent_recap, process_recap
    from recap_scheduler import _is_due, _is_recap_due, PARIS_TZ
    from sqlalchemy import text

    db.execute(text("SET LOCAL app.service_bypass = 'true'"))

    now = datetime.now(PARIS_TZ)

    # Process new Recap entities
    from database import Recap
    recaps = db.query(Recap).filter(Recap.enabled == True).all()
    results = []
    skipped = 0
    for recap in recaps:
        if not _is_recap_due(recap, now, db):
            skipped += 1
            continue
        result = process_recap(recap, db)
        results.append({"recap_id": recap.id, "recap_name": recap.name, **result})

    # Legacy agents without Recap entities
    agents = db.query(Agent).filter(Agent.weekly_recap_enabled == True).all()
    for agent in agents:
        has_recaps = db.query(Recap).filter(Recap.agent_id == agent.id).count() > 0
        if has_recaps:
            skipped += 1
            continue
        if not _is_due(agent, now, db):
            skipped += 1
            continue
        result = process_agent_recap(agent, db)
        results.append({"agent_id": agent.id, "agent_name": agent.name, **result})

    return {"processed": len(results), "skipped": skipped, "results": results}
```

- [ ] **Step 2: Update recap-preview to use first Recap if available**

In `backend/routers/agents.py`, update `recap_preview` (lines 626-664). After the agent query (line 629), add a check for Recap entities:

After:
```python
    agent = db.query(Agent).filter(Agent.id == agent_id, Agent.user_id == int(user_id)).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
```

Add:
```python
    # Redirect to first Recap entity if one exists
    from database import Recap
    first_recap = db.query(Recap).filter(Recap.agent_id == agent_id).order_by(Recap.created_at.asc()).first()
    if first_recap:
        from routers.recaps import recap_preview as _recap_preview
        return await _recap_preview(first_recap.id, user_id, db)
```

- [ ] **Step 3: Update recap-send to use first Recap if available**

In `backend/routers/agents.py`, update `recap_send` (lines 667-679). After the agent query, add:

```python
    # Redirect to first Recap entity if one exists
    from database import Recap
    first_recap = db.query(Recap).filter(Recap.agent_id == agent_id).order_by(Recap.created_at.asc()).first()
    if first_recap:
        from routers.recaps import recap_send as _recap_send
        return await _recap_send(first_recap.id, user_id, db)
```

- [ ] **Step 4: Commit**

```bash
git add backend/routers/agents.py
git commit -m "feat: update legacy recap endpoints with Recap entity fallthrough"
```

---

### Task 8: Add data migration function for existing recaps

**Files:**
- Modify: `backend/database.py`

- [ ] **Step 1: Add migrate_existing_recaps function**

In `backend/database.py`, after the `migrate_existing_company_memberships` function (around line 813), add:

```python
def migrate_existing_recaps():
    """Create Recap entities for agents that have weekly_recap_enabled=True but no Recap entities yet."""
    try:
        db = SessionLocal()
        agents = db.query(Agent).filter(Agent.weekly_recap_enabled == True).all()
        migrated = 0

        for agent in agents:
            existing = db.query(Recap).filter(Recap.agent_id == agent.id).count()
            if existing > 0:
                continue

            recap = Recap(
                agent_id=agent.id,
                company_id=agent.company_id,
                name="Recap principal",
                enabled=True,
                frequency=agent.recap_frequency or "weekly",
                hour=agent.recap_hour if agent.recap_hour is not None else 9,
                prompt=agent.weekly_recap_prompt,
                recipients=agent.weekly_recap_recipients,
            )
            db.add(recap)
            db.commit()
            db.refresh(recap)

            # Associate all existing traceability docs
            trace_docs = (
                db.query(Document)
                .filter(Document.agent_id == agent.id, Document.document_type == "traceability")
                .all()
            )
            for doc in trace_docs:
                rd = RecapDocument(
                    recap_id=recap.id,
                    document_id=doc.id,
                    included=True,
                    company_id=agent.company_id,
                )
                db.add(rd)

            db.commit()
            migrated += 1

        logger.info(f"migrate_existing_recaps: migrated {migrated} agents")
        db.close()
    except Exception as e:
        logger.error(f"migrate_existing_recaps failed: {e}")
```

- [ ] **Step 2: Call the migration in main.py startup**

In `backend/main.py`, find where `migrate_existing_company_memberships()` is called on startup, and add after it:

```python
from database import migrate_existing_recaps
migrate_existing_recaps()
```

- [ ] **Step 3: Commit**

```bash
git add backend/database.py backend/main.py
git commit -m "feat: add data migration for existing recap configs to Recap entities"
```

---

### Task 9: Frontend - Replace single recap form with multi-recap UI

**Files:**
- Modify: `frontend/pages/index.js`

- [ ] **Step 1: Add recap state variables**

In `frontend/pages/index.js`, find where the existing recap state is declared (search for `sendingRecap`). Add new state variables nearby:

```javascript
const [recaps, setRecaps] = useState([]);
const [currentRecap, setCurrentRecap] = useState(null);
const [recapDocuments, setRecapDocuments] = useState([]);
const [recapForm, setRecapForm] = useState({
  name: '',
  enabled: true,
  frequency: 'weekly',
  hour: 9,
  prompt: '',
  recipients: [],
});
const [recapRecipientInputNew, setRecapRecipientInputNew] = useState('');
const [showRecapCreate, setShowRecapCreate] = useState(false);
const [loadingRecaps, setLoadingRecaps] = useState(false);
const [savingRecap, setSavingRecap] = useState(false);
const [sendingRecapId, setSendingRecapId] = useState(null);
```

- [ ] **Step 2: Add API functions for recaps**

In `frontend/pages/index.js`, add these functions near the other API call functions (e.g. near `sendRecapNow`):

```javascript
const loadRecaps = useCallback(async (agentId) => {
  if (!agentId) return;
  setLoadingRecaps(true);
  try {
    const res = await api.get(`/api/agents/${agentId}/recaps`);
    setRecaps(res.data.recaps || []);
  } catch (err) {
    console.error('Failed to load recaps:', err);
  } finally {
    setLoadingRecaps(false);
  }
}, []);

const loadRecapDocuments = useCallback(async (recapId) => {
  try {
    const res = await api.get(`/api/recaps/${recapId}/documents`);
    setRecapDocuments(res.data.documents || []);
  } catch (err) {
    console.error('Failed to load recap documents:', err);
  }
}, []);

const createRecap = async () => {
  if (!currentAgent?.id || !recapForm.name.trim()) return;
  setSavingRecap(true);
  try {
    const res = await api.post(`/api/agents/${currentAgent.id}/recaps`, {
      name: recapForm.name,
      enabled: recapForm.enabled,
      frequency: recapForm.frequency,
      hour: recapForm.hour,
      prompt: recapForm.prompt || null,
      recipients: recapForm.recipients.length > 0 ? recapForm.recipients : null,
    });
    setRecaps(prev => [...prev, res.data.recap]);
    setShowRecapCreate(false);
    setRecapForm({ name: '', enabled: true, frequency: 'weekly', hour: 9, prompt: '', recipients: [] });
  } catch (err) {
    console.error('Failed to create recap:', err);
  } finally {
    setSavingRecap(false);
  }
};

const updateRecap = async (recapId, updates) => {
  if (!currentAgent?.id) return;
  try {
    const res = await api.put(`/api/agents/${currentAgent.id}/recaps/${recapId}`, updates);
    setRecaps(prev => prev.map(r => r.id === recapId ? res.data.recap : r));
    if (currentRecap?.id === recapId) setCurrentRecap(res.data.recap);
  } catch (err) {
    console.error('Failed to update recap:', err);
  }
};

const deleteRecap = async (recapId) => {
  if (!currentAgent?.id) return;
  try {
    await api.delete(`/api/agents/${currentAgent.id}/recaps/${recapId}`);
    setRecaps(prev => prev.filter(r => r.id !== recapId));
    if (currentRecap?.id === recapId) {
      setCurrentRecap(null);
      setRecapDocuments([]);
    }
  } catch (err) {
    console.error('Failed to delete recap:', err);
  }
};

const toggleRecapDocument = async (recapId, documentId, included) => {
  try {
    await api.put(`/api/recaps/${recapId}/documents/${documentId}`, { included });
    setRecapDocuments(prev =>
      prev.map(d => d.document_id === documentId ? { ...d, included } : d)
    );
  } catch (err) {
    console.error('Failed to toggle recap document:', err);
  }
};

const sendRecapById = async (recapId) => {
  setSendingRecapId(recapId);
  try {
    const res = await api.post(`/api/recaps/${recapId}/send`);
    if (res.data.status === 'success') {
      alert(`Recap envoyé à ${res.data.email}`);
    } else if (res.data.status === 'no_data') {
      alert('Aucune donnée pour cette période');
    }
  } catch (err) {
    console.error('Failed to send recap:', err);
    alert('Erreur lors de l\'envoi du recap');
  } finally {
    setSendingRecapId(null);
  }
};
```

- [ ] **Step 3: Load recaps when agent is selected**

In `frontend/pages/index.js`, find where agent data is loaded when an agent is selected (search for `loadAgentData` or the useEffect that fires when `urlAgentId` changes). Add a call to `loadRecaps`:

```javascript
loadRecaps(urlAgentId);
```

- [ ] **Step 4: Replace the recap settings JSX**

In `frontend/pages/index.js`, find the Weekly Recap section (search for `Weekly Recap` or `weeklyRecap` around lines 1198-1334). Replace the entire `{/* Weekly Recap */}` div with:

```jsx
{/* Multi-Recap Section */}
<div className="mt-6 p-4 bg-gradient-to-br from-amber-50 to-orange-50 rounded-button border border-amber-200">
  <div className="flex items-center justify-between mb-3">
    <p className="text-sm font-semibold text-gray-700 flex items-center">
      <Mail className="w-4 h-4 mr-2 text-amber-600" />
      Recaps
    </p>
    <button
      type="button"
      onClick={() => setShowRecapCreate(true)}
      className="flex items-center gap-1 px-3 py-1.5 bg-amber-500 hover:bg-amber-600 text-white text-xs font-medium rounded-sm transition-colors"
    >
      <Plus className="w-3.5 h-3.5" /> Nouveau recap
    </button>
  </div>

  {/* Create Form */}
  {showRecapCreate && (
    <div className="mb-3 p-3 bg-white rounded-sm border border-amber-200">
      <input
        type="text"
        className="w-full px-3 py-2 border border-amber-200 rounded-sm text-sm mb-2"
        placeholder="Nom du recap..."
        value={recapForm.name}
        onChange={e => setRecapForm(f => ({ ...f, name: e.target.value }))}
      />
      <div className="grid grid-cols-2 gap-2 mb-2">
        <select
          className="px-3 py-2 border border-amber-200 rounded-sm text-sm bg-white"
          value={recapForm.frequency}
          onChange={e => setRecapForm(f => ({ ...f, frequency: e.target.value }))}
        >
          {["daily", "weekly", "monthly"].map(freq => (
            <option key={freq} value={freq}>
              {t(`agents:form.weeklyRecap.frequencyOptions.${freq}`)}
            </option>
          ))}
        </select>
        <select
          className="px-3 py-2 border border-amber-200 rounded-sm text-sm bg-white"
          value={recapForm.hour}
          onChange={e => setRecapForm(f => ({ ...f, hour: parseInt(e.target.value, 10) }))}
        >
          {Array.from({ length: 24 }, (_, i) => (
            <option key={i} value={i}>{i}h</option>
          ))}
        </select>
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={createRecap}
          disabled={savingRecap || !recapForm.name.trim()}
          className="px-4 py-1.5 bg-amber-500 hover:bg-amber-600 disabled:bg-amber-300 text-white text-sm rounded-sm transition-colors"
        >
          {savingRecap ? 'Création...' : 'Créer'}
        </button>
        <button
          type="button"
          onClick={() => { setShowRecapCreate(false); setRecapForm({ name: '', enabled: true, frequency: 'weekly', hour: 9, prompt: '', recipients: [] }); }}
          className="px-4 py-1.5 bg-gray-200 hover:bg-gray-300 text-gray-700 text-sm rounded-sm transition-colors"
        >
          Annuler
        </button>
      </div>
    </div>
  )}

  {/* Recap List */}
  {loadingRecaps ? (
    <p className="text-xs text-gray-400 text-center py-4">Chargement...</p>
  ) : recaps.length === 0 && !showRecapCreate ? (
    <p className="text-xs text-gray-400 text-center py-4">Aucun recap configuré</p>
  ) : (
    <div className="space-y-2">
      {recaps.map(recap => (
        <div key={recap.id} className="bg-white rounded-sm border border-amber-100 overflow-hidden">
          {/* Recap Header */}
          <div
            className="flex items-center justify-between p-3 cursor-pointer hover:bg-amber-50 transition-colors"
            onClick={() => {
              if (currentRecap?.id === recap.id) {
                setCurrentRecap(null);
                setRecapDocuments([]);
              } else {
                setCurrentRecap(recap);
                loadRecapDocuments(recap.id);
              }
            }}
          >
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${recap.enabled ? 'bg-green-400' : 'bg-gray-300'}`} />
              <span className="text-sm font-medium text-gray-700">{recap.name}</span>
              <span className="text-xs text-gray-400">
                {recap.frequency === 'daily' ? 'Quotidien' : recap.frequency === 'weekly' ? 'Hebdo' : 'Mensuel'} - {recap.hour}h
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-400">{recap.document_count} docs</span>
              <ChevronDown className={`w-4 h-4 text-gray-400 transition-transform ${currentRecap?.id === recap.id ? 'rotate-180' : ''}`} />
            </div>
          </div>

          {/* Recap Detail (expanded) */}
          {currentRecap?.id === recap.id && (
            <div className="border-t border-amber-100 p-3 space-y-3">
              {/* Toggle enabled */}
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-gray-600">Activé</span>
                <button
                  type="button"
                  className={`w-12 h-6 flex items-center rounded-full px-0.5 transition-colors ${recap.enabled ? 'bg-amber-500' : 'bg-gray-200'}`}
                  onClick={() => updateRecap(recap.id, { enabled: !recap.enabled })}
                >
                  <span className={`h-5 w-5 rounded-full bg-white shadow transition-transform ${recap.enabled ? 'translate-x-6' : 'translate-x-0'}`} />
                </button>
              </div>

              {/* Name */}
              <div>
                <label className="text-xs font-semibold text-gray-600 mb-1 block">Nom</label>
                <input
                  type="text"
                  className="w-full px-3 py-1.5 border border-amber-200 rounded-sm text-sm"
                  defaultValue={recap.name}
                  onBlur={e => {
                    if (e.target.value.trim() && e.target.value !== recap.name) {
                      updateRecap(recap.id, { name: e.target.value.trim() });
                    }
                  }}
                />
              </div>

              {/* Frequency + Hour */}
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs font-semibold text-gray-600 mb-1 block">Fréquence</label>
                  <select
                    className="w-full px-3 py-1.5 border border-amber-200 rounded-sm text-sm bg-white"
                    value={recap.frequency}
                    onChange={e => updateRecap(recap.id, { frequency: e.target.value })}
                  >
                    {["daily", "weekly", "monthly"].map(freq => (
                      <option key={freq} value={freq}>
                        {t(`agents:form.weeklyRecap.frequencyOptions.${freq}`)}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-600 mb-1 block">Heure</label>
                  <select
                    className="w-full px-3 py-1.5 border border-amber-200 rounded-sm text-sm bg-white"
                    value={recap.hour}
                    onChange={e => updateRecap(recap.id, { hour: parseInt(e.target.value, 10) })}
                  >
                    {Array.from({ length: 24 }, (_, i) => (
                      <option key={i} value={i}>{i}h</option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Custom Prompt */}
              <div>
                <label className="text-xs font-semibold text-gray-600 mb-1 block">Prompt personnalisé</label>
                <textarea
                  className="w-full px-3 py-1.5 border border-amber-200 rounded-sm text-sm resize-y"
                  rows={3}
                  placeholder="Personnalisez le contenu du recap..."
                  defaultValue={recap.prompt || ''}
                  onBlur={e => {
                    const val = e.target.value.trim();
                    if (val !== (recap.prompt || '')) {
                      updateRecap(recap.id, { prompt: val || null });
                    }
                  }}
                />
              </div>

              {/* Recipients */}
              <div>
                <label className="text-xs font-semibold text-gray-600 mb-1 block">
                  <Users className="w-3.5 h-3.5 inline mr-1 text-amber-600" />
                  Destinataires supplémentaires
                </label>
                <div className="flex gap-2">
                  <input
                    type="email"
                    className="flex-1 px-3 py-1.5 border border-amber-200 rounded-sm text-sm"
                    placeholder="email@exemple.com"
                    value={recapRecipientInputNew}
                    onChange={e => setRecapRecipientInputNew(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        const email = recapRecipientInputNew.trim();
                        if (email && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) && !(recap.recipients || []).includes(email)) {
                          updateRecap(recap.id, { recipients: [...(recap.recipients || []), email] });
                          setRecapRecipientInputNew('');
                        }
                      }
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => {
                      const email = recapRecipientInputNew.trim();
                      if (email && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) && !(recap.recipients || []).includes(email)) {
                        updateRecap(recap.id, { recipients: [...(recap.recipients || []), email] });
                        setRecapRecipientInputNew('');
                      }
                    }}
                    className="px-3 py-1.5 bg-amber-500 hover:bg-amber-600 text-white text-sm rounded-sm"
                  >
                    <Plus className="w-4 h-4" />
                  </button>
                </div>
                {(recap.recipients || []).length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {(recap.recipients || []).map((email, i) => (
                      <span key={i} className="inline-flex items-center gap-1 px-2 py-1 bg-amber-100 text-amber-800 text-xs rounded-full">
                        <Mail className="w-3 h-3" />
                        {email}
                        <button
                          type="button"
                          onClick={() => updateRecap(recap.id, { recipients: recap.recipients.filter((_, idx) => idx !== i) })}
                          className="ml-0.5 hover:text-red-600"
                        >
                          <XCircle className="w-3.5 h-3.5" />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Documents */}
              <div>
                <label className="text-xs font-semibold text-gray-600 mb-1 block">Documents</label>
                {recapDocuments.length === 0 ? (
                  <p className="text-xs text-gray-400">Aucun document de traçabilité</p>
                ) : (
                  <div className="max-h-48 overflow-y-auto space-y-1">
                    {recapDocuments.map(doc => (
                      <div key={doc.document_id} className="flex items-center justify-between p-2 bg-gray-50 rounded-sm">
                        <span className="text-xs text-gray-700 truncate flex-1 mr-2">{doc.filename}</span>
                        <button
                          type="button"
                          className={`w-10 h-5 flex items-center rounded-full px-0.5 transition-colors ${doc.included ? 'bg-amber-500' : 'bg-gray-200'}`}
                          onClick={() => toggleRecapDocument(recap.id, doc.document_id, !doc.included)}
                        >
                          <span className={`h-4 w-4 rounded-full bg-white shadow transition-transform ${doc.included ? 'translate-x-5' : 'translate-x-0'}`} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Action Buttons */}
              <div className="flex gap-2 pt-2 border-t border-amber-100">
                <button
                  type="button"
                  onClick={() => sendRecapById(recap.id)}
                  disabled={sendingRecapId === recap.id}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-amber-500 hover:bg-amber-600 disabled:bg-amber-300 text-white text-sm font-medium rounded-sm transition-colors"
                >
                  {sendingRecapId === recap.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                  {sendingRecapId === recap.id ? 'Envoi...' : 'Envoyer maintenant'}
                </button>
                <button
                  type="button"
                  onClick={() => { if (confirm('Supprimer ce recap ?')) deleteRecap(recap.id); }}
                  className="px-4 py-2 bg-red-100 hover:bg-red-200 text-red-600 text-sm font-medium rounded-sm transition-colors"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  )}
</div>
```

- [ ] **Step 5: Remove old recap fields from the auto-save form data**

In `frontend/pages/index.js`, in the `saveAgent` function (around lines 355-361), remove the lines that send old recap fields. Remove:

```javascript
formData.append("weekly_recap_enabled", f.weekly_recap_enabled ? "true" : "false");
if (f.weekly_recap_prompt) formData.append("weekly_recap_prompt", f.weekly_recap_prompt);
if (f.weekly_recap_recipients && f.weekly_recap_recipients.length > 0) {
  formData.append("weekly_recap_recipients", JSON.stringify(f.weekly_recap_recipients));
}
formData.append("recap_frequency", f.recap_frequency);
formData.append("recap_hour", String(f.recap_hour));
```

Note: The backend update_agent still accepts these fields for compatibility, they just won't be actively used for agents that have Recap entities.

- [ ] **Step 6: Verify the frontend builds**

```bash
cd frontend && npm run lint
```

- [ ] **Step 7: Commit**

```bash
git add frontend/pages/index.js
git commit -m "feat: replace single recap form with multi-recap UI"
```

---

### Task 10: Verify icons used in frontend

**Files:**
- Modify: `frontend/pages/index.js` (imports if needed)

- [ ] **Step 1: Check that all icons used in the new JSX are imported**

Search the imports at the top of `frontend/pages/index.js` for:
- `Mail` - should already be imported (used in old recap)
- `Plus` - should already be imported
- `XCircle` - should already be imported
- `Users` - should already be imported
- `Send` - should already be imported
- `Loader2` - should already be imported
- `ChevronDown` - check if imported from lucide-react; if not, add it
- `Trash2` - check if imported from lucide-react; if not, add it

If missing, add to the existing lucide-react import line:

```javascript
import { ..., ChevronDown, Trash2 } from "lucide-react";
```

- [ ] **Step 2: Commit if changes were made**

```bash
git add frontend/pages/index.js
git commit -m "fix: add missing icon imports for multi-recap UI"
```
