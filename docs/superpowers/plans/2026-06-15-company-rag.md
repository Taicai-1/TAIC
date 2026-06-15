# RAG Entreprise Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an organization maintain a shared "company RAG" document store (managed on the Organisation page by owners/admins) that any agent can opt into via a single toggle.

**Architecture:** A company document is a normal `Document` row flagged `is_company_rag=True` with `agent_id=NULL`. It reuses the entire existing chunk/embed/pgvector pipeline. Retrieval (`search_similar_texts_for_user`) excludes company docs by default and unions them in only when the agent's `include_company_rag` flag is on, all under the existing hard `company_id` tenant filter. A new `routers/company_rag.py` exposes list/upload/delete; the agent toggle rides the existing form-param + serialization pattern.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL + pgvector, Next.js 14 (Pages Router), React 18, Tailwind, react-i18next, pytest (DB-backed harness in `backend/tests/`).

**Spec:** `docs/superpowers/specs/2026-06-15-company-rag-design.md`

**Branch:** `feature/company-rag` (already created).

---

## File Structure

**Backend**
- `backend/database.py` — add `Document.is_company_rag` + `Agent.include_company_rag` model columns and two `migrations` rows.
- `backend/rag_engine.py` — `search_similar_texts_for_user` scope filters + `get_answer`/`get_answer_stream` wiring; thread `is_company_rag` through `ingest_text_content` and `process_document_for_user`.
- `backend/routers/documents.py` — thread `is_company_rag` through `_process_document_background`; allow same-company members to download company docs.
- `backend/routers/company_rag.py` — **new** router: list / upload / delete company RAG documents.
- `backend/routers/agents.py` — `include_company_rag` form param (create + update) and serialization.
- `backend/main.py` — register the new router.
- `backend/tests/test_company_rag.py` — **new** tests (retrieval + endpoints).
- `backend/tests/test_endpoints_agents.py` — extend with toggle round-trip test.

**Frontend**
- `frontend/pages/agents.js` — toggle in the agent create/edit modal.
- `frontend/pages/organization.js` — "RAG Entreprise" section.
- `frontend/public/locales/{fr,en}/organization.json` — section keys.
- `frontend/public/locales/{fr,en}/agents.json` — toggle keys.

---

## Task 1: Database columns & models

**Files:**
- Modify: `backend/database.py` (Agent model ~line 327; Document model ~line 549; `migrations` list ~line 1011)

- [ ] **Step 1: Add the model columns**

In the `Agent` class, after the `date_awareness_enabled` column (~line 327):

```python
    # Date awareness: inject current date/time into system prompt
    date_awareness_enabled = Column(Boolean, default=False, nullable=False)

    # Company RAG: include the organization's shared documents in this agent's retrieval
    include_company_rag = Column(Boolean, default=False, nullable=False)
```

In the `Document` class, after the `mission_id` column (~line 552):

```python
    mission_id = Column(
        Integer, ForeignKey("missions.id", ondelete="CASCADE"), nullable=True, index=True
    )  # Documents siloed to a mission (RAG sources)
    is_company_rag = Column(
        Boolean, default=False, nullable=False, server_default="false", index=True
    )  # Company-shared document (agent_id is NULL); included only when an agent opts in
```

- [ ] **Step 2: Register both columns in the `ensure_columns` migration list**

In `database.py`, inside the `migrations` list, after the `# Missions` block (~line 1015):

```python
        # Missions
        ("documents", "mission_id", "INTEGER REFERENCES missions(id) ON DELETE CASCADE"),
        ("conversations", "mission_id", "INTEGER REFERENCES missions(id) ON DELETE CASCADE"),
        # Company RAG
        ("documents", "is_company_rag", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("agents", "include_company_rag", "BOOLEAN NOT NULL DEFAULT FALSE"),
```

- [ ] **Step 3: Write a model round-trip test**

Create `backend/tests/test_company_rag.py`:

```python
"""Tests for the company RAG feature (shared org documents + per-agent inclusion)."""

import pytest


@pytest.mark.asyncio
async def test_company_rag_columns_default_false(db_session, test_company):
    """New columns exist and default to False."""
    from tests.factories import UserFactory, AgentFactory, DocumentFactory

    user = UserFactory.build(company_id=test_company.id)
    db_session.add(user)
    db_session.flush()

    agent = AgentFactory.build(user_id=user.id, company_id=test_company.id)
    db_session.add(agent)
    db_session.flush()

    doc = DocumentFactory.build(user_id=user.id, company_id=test_company.id)
    db_session.add(doc)
    db_session.flush()

    assert agent.include_company_rag is False
    assert doc.is_company_rag is False
```

- [ ] **Step 4: Run the test**

Run: `cd backend && python -m pytest tests/test_company_rag.py::test_company_rag_columns_default_false -v`
Expected: PASS (or SKIP if PostgreSQL is not reachable — that is acceptable; CI provides PG).

- [ ] **Step 5: Commit**

```bash
git add backend/database.py backend/tests/test_company_rag.py
git commit -m "feat(company-rag): add is_company_rag and include_company_rag columns"
```

---

## Task 2: Thread `is_company_rag` through the ingestion pipeline

**Files:**
- Modify: `backend/rag_engine.py` (`ingest_text_content` ~line 984; `process_document_for_user` ~line 1084)
- Modify: `backend/routers/documents.py` (`_process_document_background` ~line 565)

- [ ] **Step 1: Add the param to `ingest_text_content` and set it on the Document**

Change the signature (add `is_company_rag` after `mission_id`):

```python
def ingest_text_content(
    text_content: str,
    filename: str,
    user_id: int,
    agent_id: int,
    db: Session,
    gcs_url: str = None,
    notion_link_id: int = None,
    company_id: int = None,
    drive_link_id: int = None,
    drive_file_id: str = None,
    progress_callback=None,
    mission_id: int = None,
    is_company_rag: bool = False,
) -> int:
```

In the `Document(...)` construction (~line 1023), add the field:

```python
        document = Document(
            filename=filename,
            content=text_content,
            user_id=user_id,
            agent_id=agent_id,
            company_id=company_id,
            gcs_url=gcs_url,
            notion_link_id=notion_link_id,
            drive_link_id=drive_link_id,
            drive_file_id=drive_file_id,
            mission_id=mission_id,
            is_company_rag=is_company_rag,
        )
```

- [ ] **Step 2: Add the param to `process_document_for_user` and forward it**

Change the signature (add `is_company_rag` after `mission_id`):

```python
def process_document_for_user(
    filename: str,
    content: bytes,
    user_id: int,
    db: Session,
    agent_id: int = None,
    company_id: int = None,
    progress_callback=None,
    mission_id: int = None,
    is_company_rag: bool = False,
) -> int:
```

In its `return ingest_text_content(...)` call (~line 1146), add the kwarg:

```python
        return ingest_text_content(
            text_content,
            filename,
            user_id,
            agent_id,
            db,
            gcs_url=gcs_url,
            company_id=company_id,
            progress_callback=progress_callback,
            mission_id=mission_id,
            is_company_rag=is_company_rag,
        )
```

- [ ] **Step 3: Thread it through the async background worker**

In `backend/routers/documents.py`, change `_process_document_background` signature (~line 565) to add `is_company_rag`:

```python
def _process_document_background(
    task_id: str,
    filename: str,
    content: bytes,
    user_id: int,
    agent_id: int,
    company_id: int = None,
    mission_id: int = None,
    is_company_rag: bool = False,
):
```

And in its `process_document_for_user(...)` call (~line 618), add the kwarg:

```python
        doc_id = process_document_for_user(
            filename,
            content,
            user_id,
            db,
            agent_id,
            company_id=company_id,
            progress_callback=_report_progress,
            mission_id=mission_id,
            is_company_rag=is_company_rag,
        )
```

- [ ] **Step 4: Run existing ingestion/document tests to confirm no regression**

Run: `cd backend && python -m pytest tests/test_rag_engine.py tests/test_endpoints_documents.py -v`
Expected: PASS or SKIP (no failures). Existing callers use the default `is_company_rag=False`.

- [ ] **Step 5: Commit**

```bash
git add backend/rag_engine.py backend/routers/documents.py
git commit -m "feat(company-rag): thread is_company_rag through ingestion pipeline"
```

---

## Task 3: Retrieval scoping

**Files:**
- Modify: `backend/rag_engine.py` (imports near top; `search_similar_texts_for_user` ~line 771; `get_answer` ~line 226; `get_answer_stream` ~line 508)
- Test: `backend/tests/test_company_rag.py`

- [ ] **Step 1: Write the failing retrieval test**

Append to `backend/tests/test_company_rag.py`:

```python
def _seed_company_doc_with_chunk(db_session, company, user, vec):
    """Create a company RAG document with one embedded chunk. Returns the Document."""
    from tests.factories import DocumentFactory, DocumentChunkFactory

    doc = DocumentFactory.build(
        user_id=user.id,
        agent_id=None,
        company_id=company.id,
        is_company_rag=True,
        filename="company-handbook.txt",
    )
    db_session.add(doc)
    db_session.flush()

    chunk = DocumentChunkFactory.build(
        document_id=doc.id,
        company_id=company.id,
        chunk_text="The company travel policy reimburses economy flights.",
        embedding_vec=vec,
        chunk_index=0,
    )
    db_session.add(chunk)
    db_session.flush()
    return doc


@pytest.mark.asyncio
async def test_company_doc_excluded_when_toggle_off(db_session, test_company):
    from rag_engine import search_similar_texts_for_user
    from tests.factories import UserFactory, AgentFactory

    user = UserFactory.build(company_id=test_company.id)
    db_session.add(user)
    db_session.flush()
    agent = AgentFactory.build(user_id=user.id, company_id=test_company.id)
    db_session.add(agent)
    db_session.flush()

    vec = [1.0] + [0.0] * 1023
    _seed_company_doc_with_chunk(db_session, test_company, user, vec)

    results = search_similar_texts_for_user(
        query_embedding=vec, user_id=user.id, db=db_session,
        top_k=5, agent_id=agent.id, company_id=test_company.id,
        include_company_rag=False,
    )
    assert results == []


@pytest.mark.asyncio
async def test_company_doc_included_when_toggle_on(db_session, test_company):
    from rag_engine import search_similar_texts_for_user
    from tests.factories import UserFactory, AgentFactory

    user = UserFactory.build(company_id=test_company.id)
    db_session.add(user)
    db_session.flush()
    agent = AgentFactory.build(user_id=user.id, company_id=test_company.id)
    db_session.add(agent)
    db_session.flush()

    vec = [1.0] + [0.0] * 1023
    doc = _seed_company_doc_with_chunk(db_session, test_company, user, vec)

    results = search_similar_texts_for_user(
        query_embedding=vec, user_id=user.id, db=db_session,
        top_k=5, agent_id=agent.id, company_id=test_company.id,
        include_company_rag=True,
    )
    assert any(r["document_id"] == doc.id for r in results)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_company_rag.py -k "toggle" -v`
Expected: FAIL — `search_similar_texts_for_user() got an unexpected keyword argument 'include_company_rag'` (or SKIP if no PG; if SKIP, proceed and rely on CI).

- [ ] **Step 3: Add the SQLAlchemy `and_`/`or_` import**

At the top of `backend/rag_engine.py`, near the existing `from sqlalchemy.orm import Session` (line 8), add:

```python
from sqlalchemy import and_, or_
```

- [ ] **Step 4: Add the param and update the scope filters**

Change the `search_similar_texts_for_user` signature (~line 771) to add `include_company_rag`:

```python
def search_similar_texts_for_user(
    query_embedding: List[float],
    user_id: int,
    db: Session,
    top_k: int = 3,
    selected_doc_ids: List[int] = None,
    agent_id: int = None,
    company_id: int = None,
    mission_id: int = None,
    include_company_rag: bool = False,
) -> List[dict]:
```

Replace the scope-filter block (~lines 839-846) with:

```python
        if mission_id:
            query = query.filter(Document.mission_id == mission_id)
        elif agent_id:
            # Agent-scoped docs; optionally union the company-shared docs
            agent_scope = and_(Document.agent_id == agent_id, Document.mission_id.is_(None))
            if include_company_rag:
                query = query.filter(or_(agent_scope, Document.is_company_rag.is_(True)))
            else:
                query = query.filter(agent_scope, Document.is_company_rag.is_(False))
        else:
            # User-level general RAG: never leak company docs into personal scope
            query = query.filter(
                Document.user_id == user_id,
                Document.mission_id.is_(None),
                Document.is_company_rag.is_(False),
            )
```

- [ ] **Step 5: Run the retrieval tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_company_rag.py -k "toggle" -v`
Expected: PASS (or SKIP without PG).

- [ ] **Step 6: Wire the flag into `get_answer`**

In `get_answer` (~line 226), locate where the agent is loaded and where `search_similar_texts_for_user(...)` is called (~line 416). Just before that call, resolve the flag from the agent, then pass it. If the agent object is already loaded as `agent`, add:

```python
        include_company_rag = bool(getattr(agent, "include_company_rag", False)) if agent else False
```

(If `agent` is not in scope at that point, load it: `agent = db.query(Agent).filter(Agent.id == agent_id).first() if agent_id else None`.)

Then update the call (~line 416):

```python
        context_results = search_similar_texts_for_user(
            query_embedding,
            user_id,
            db,
            top_k=top_k,
            selected_doc_ids=selected_doc_ids,
            agent_id=agent_id,
            company_id=company_id,
            include_company_rag=include_company_rag,
        )
```

(Keep the existing argument names/order already present at that call site; only add `include_company_rag=include_company_rag`.)

- [ ] **Step 7: Extend the "available documents" list to include company docs**

In `get_answer`, where `user_docs` is built for the agent branch (~lines 263-267), the query is:

```python
                .filter(Document.agent_id == agent_id, Document.document_type != "traceability")
```

Replace that agent-branch filter so company docs are listed when the toggle is on:

```python
                .filter(
                    or_(
                        Document.agent_id == agent_id,
                        Document.is_company_rag.is_(True) if include_company_rag else False,
                    ),
                    Document.document_type != "traceability",
                )
```

Compute `include_company_rag` (Step 6) before this block so it is in scope. Ensure the user-scope branch (`Document.user_id == user_id`, ~line 273) additionally filters `Document.is_company_rag.is_(False)` so personal listings never show company docs:

```python
                .filter(
                    Document.user_id == user_id,
                    Document.document_type != "traceability",
                    Document.is_company_rag.is_(False),
                )
```

- [ ] **Step 8: Mirror the same wiring in `get_answer_stream`**

`get_answer_stream` (~line 508) duplicates the doc-selection and search logic (~lines 529-550). Apply the identical changes: compute `include_company_rag` from the agent, pass it to `search_similar_texts_for_user`, and apply the same `or_(...)` agent-branch filter and the `is_company_rag.is_(False)` user-branch filter.

- [ ] **Step 9: Run the full rag test module**

Run: `cd backend && python -m pytest tests/test_company_rag.py tests/test_rag_engine.py tests/test_endpoints_ask.py -v`
Expected: PASS or SKIP, no failures.

- [ ] **Step 10: Commit**

```bash
git add backend/rag_engine.py backend/tests/test_company_rag.py
git commit -m "feat(company-rag): include company docs in retrieval when agent opts in"
```

---

## Task 4: Agent endpoint — toggle param & serialization

**Files:**
- Modify: `backend/routers/agents.py` (create_agent ~line 154/246; update_agent ~line 689/752; get_agent serialization ~line 320; list serialization ~lines 105/135)
- Test: `backend/tests/test_endpoints_agents.py`

- [ ] **Step 1: Write the failing round-trip test**

Append to `backend/tests/test_endpoints_agents.py` (follow the file's existing fixture style — `client`, `admin_cookies`, `test_admin_user`):

```python
@pytest.mark.asyncio
async def test_create_agent_include_company_rag_roundtrips(client, admin_cookies, test_admin_user):
    """include_company_rag set at creation is returned by GET."""
    resp = await client.post(
        "/agents",
        data={"name": "RAG Agent", "contexte": "ctx", "type": "conversationnel",
              "include_company_rag": "true"},
        cookies=admin_cookies,
    )
    assert resp.status_code == 200
    agent_id = resp.json()["id"]

    got = await client.get(f"/agents/{agent_id}", cookies=admin_cookies)
    assert got.status_code == 200
    assert got.json()["include_company_rag"] is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_endpoints_agents.py::test_create_agent_include_company_rag_roundtrips -v`
Expected: FAIL (`include_company_rag` missing / KeyError) or SKIP without PG.

- [ ] **Step 3: Add the form param to `create_agent`**

In `create_agent` (~line 154), add after `date_awareness_enabled: str = Form("false"),` (~line 168):

```python
    date_awareness_enabled: str = Form("false"),
    include_company_rag: str = Form("false"),
```

In the `Agent(...)` creation (where `date_awareness_enabled=...` is set, ~line 246), add:

```python
            date_awareness_enabled=date_awareness_enabled.lower() in ("true", "1", "yes"),
            include_company_rag=include_company_rag.lower() in ("true", "1", "yes"),
```

- [ ] **Step 4: Add the form param to `update_agent`**

In `update_agent` (~line 689), add after `date_awareness_enabled: str = Form("false"),` (~line 704):

```python
    date_awareness_enabled: str = Form("false"),
    include_company_rag: str = Form("false"),
```

Where `agent.date_awareness_enabled = ...` is assigned (~line 752), add:

```python
        agent.date_awareness_enabled = date_awareness_enabled.lower() in ("true", "1", "yes")
        agent.include_company_rag = include_company_rag.lower() in ("true", "1", "yes")
```

- [ ] **Step 5: Add to serialization (GET single + list)**

In `get_agent` result dict (~line 327) add the field to the base `result`:

```python
            "date_awareness_enabled": agent.date_awareness_enabled,
            "include_company_rag": getattr(agent, "include_company_rag", False),
```

In the list endpoint serialization (~lines 105 and 135, the two dicts that expose `date_awareness_enabled`), add alongside each:

```python
                "include_company_rag": getattr(a, "include_company_rag", False),
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/test_endpoints_agents.py::test_create_agent_include_company_rag_roundtrips -v`
Expected: PASS (or SKIP without PG).

- [ ] **Step 7: Commit**

```bash
git add backend/routers/agents.py backend/tests/test_endpoints_agents.py
git commit -m "feat(company-rag): add include_company_rag to agent create/update/serialize"
```

---

## Task 5: Company RAG router (list / upload / delete)

**Files:**
- Create: `backend/routers/company_rag.py`
- Modify: `backend/main.py` (router registration)
- Test: `backend/tests/test_company_rag.py`

- [ ] **Step 1: Write the failing endpoint tests**

Append to `backend/tests/test_company_rag.py`:

```python
from pathlib import Path
from unittest.mock import patch


@pytest.mark.asyncio
async def test_member_cannot_upload_company_doc(client, member_cookies):
    files = {"file": ("policy.txt", b"hello company", "text/plain")}
    resp = await client.post("/api/company-rag/documents", files=files, cookies=member_cookies)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_uploads_company_doc(client, admin_cookies, test_admin_user, mock_redis_none, mock_event_tracker):
    with patch("routers.company_rag.process_document_for_user", return_value=777) as mock_proc:
        files = {"file": ("policy.txt", b"hello company", "text/plain")}
        resp = await client.post("/api/company-rag/documents", files=files, cookies=admin_cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_id"] == 777
    # Uploaded as a company doc, not tied to an agent
    kwargs = mock_proc.call_args.kwargs
    assert kwargs["is_company_rag"] is True
    assert kwargs["agent_id"] is None
    assert kwargs["company_id"] == test_admin_user.company_id


@pytest.mark.asyncio
async def test_member_can_list_company_docs(client, member_cookies, db_session, test_company, test_member_user):
    from tests.factories import DocumentFactory
    doc = DocumentFactory.build(
        user_id=test_member_user.id, agent_id=None, company_id=test_company.id,
        is_company_rag=True, filename="shared.txt",
    )
    db_session.add(doc)
    db_session.flush()

    resp = await client.get("/api/company-rag/documents", cookies=member_cookies)
    assert resp.status_code == 200
    names = [d["filename"] for d in resp.json()["documents"]]
    assert "shared.txt" in names


@pytest.mark.asyncio
async def test_admin_deletes_company_doc(client, admin_cookies, db_session, test_admin_user):
    from tests.factories import DocumentFactory
    doc = DocumentFactory.build(
        user_id=test_admin_user.id, agent_id=None, company_id=test_admin_user.company_id,
        is_company_rag=True, filename="to-delete.txt",
    )
    db_session.add(doc)
    db_session.flush()

    resp = await client.delete(f"/api/company-rag/documents/{doc.id}", cookies=admin_cookies)
    assert resp.status_code == 200
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && python -m pytest tests/test_company_rag.py -k "company_doc" -v`
Expected: FAIL (404 — route not registered) or SKIP without PG.

- [ ] **Step 3: Create the router**

Create `backend/routers/company_rag.py`:

```python
"""Company RAG endpoints: shared organization documents (list / upload / delete).

Company documents are normal Document rows flagged is_company_rag=True with
agent_id=NULL. Any company member may list/download them; only owners/admins
may upload or delete. Tenant boundary is the caller's company_id.
"""

import json
import logging
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from auth import verify_token
from database import get_db, Document, User
from permissions import require_role
from rag_engine import process_document_for_user
from redis_client import get_redis
from routers.documents import _process_document_background, MAX_FILE_SIZE
from utils import event_tracker

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_TYPES = [".pdf", ".txt", ".docx", ".ics", ".json"]


def _caller_company_id(user_id: str, db: Session) -> int:
    """Return the caller's company_id or raise 400 if they belong to no company."""
    row = db.query(User.company_id).filter(User.id == int(user_id)).first()
    if not row or row[0] is None:
        raise HTTPException(status_code=400, detail="You are not part of an organization")
    return row[0]


@router.get("/api/company-rag/documents")
async def list_company_documents(
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """List the organization's shared RAG documents (any member)."""
    company_id = _caller_company_id(user_id, db)
    docs = (
        db.query(Document)
        .filter(Document.company_id == company_id, Document.is_company_rag.is_(True))
        .order_by(Document.created_at.desc())
        .all()
    )
    return {
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "source_url": d.source_url,
                "document_type": d.document_type,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ]
    }


@router.post("/api/company-rag/documents")
async def upload_company_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Upload a shared company RAG document (owner/admin only)."""
    require_role(int(user_id), db, "admin")
    company_id = _caller_company_id(user_id, db)

    if file.size and file.size > MAX_FILE_SIZE:
        max_mb = MAX_FILE_SIZE / (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"File too large (max {max_mb:.0f}MB)")
    if not any(file.filename.lower().endswith(ext) for ext in ALLOWED_TYPES):
        raise HTTPException(status_code=400, detail="File type not supported")

    content = await file.read()

    r = get_redis()
    if r is not None:
        task_id = str(uuid4())
        r.setex(
            f"doc_task:{task_id}",
            3600,
            json.dumps({
                "task_id": task_id, "status": "processing",
                "filename": file.filename, "document_id": None, "error": None,
            }),
        )
        background_tasks.add_task(
            _process_document_background,
            task_id, file.filename, content, int(user_id), None, company_id, None, True,
        )
        return {"filename": file.filename, "task_id": task_id, "status": "processing"}

    doc_id = process_document_for_user(
        file.filename, content, int(user_id), db,
        agent_id=None, company_id=company_id, is_company_rag=True,
    )
    event_tracker.track_document_upload(int(user_id), file.filename, len(content))
    return {"filename": file.filename, "document_id": doc_id, "status": "uploaded"}


@router.delete("/api/company-rag/documents/{document_id}")
async def delete_company_document(
    document_id: int,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Delete a shared company RAG document (owner/admin only). Chunks cascade."""
    require_role(int(user_id), db, "admin")
    company_id = _caller_company_id(user_id, db)

    doc = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.company_id == company_id,
            Document.is_company_rag.is_(True),
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Company document not found")

    db.delete(doc)
    db.commit()
    return {"status": "deleted", "id": document_id}
```

Note: confirm the `_process_document_background` positional order matches Task 2's signature `(task_id, filename, content, user_id, agent_id, company_id, mission_id, is_company_rag)` — the call passes `None` for `agent_id`, `company_id`, `None` for `mission_id`, `True` for `is_company_rag`. Confirm `MAX_FILE_SIZE` and `event_tracker` import paths match `routers/documents.py` (it imports `from utils import event_tracker` and defines/imports `MAX_FILE_SIZE`); if `MAX_FILE_SIZE` is not importable from `routers.documents`, import it from the same module `routers/documents.py` imports it from.

- [ ] **Step 4: Register the router in `main.py`**

Find where the other routers are included (e.g. `app.include_router(documents.router)` / `agents.router`) in `backend/main.py` and add:

```python
from routers import company_rag
app.include_router(company_rag.router)
```

Match the exact include style used for the neighboring routers (some use `from routers import X`, some `app.include_router(X.router, tags=[...])`).

- [ ] **Step 5: Run the endpoint tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_company_rag.py -k "company_doc" -v`
Expected: PASS (or SKIP without PG).

- [ ] **Step 6: Commit**

```bash
git add backend/routers/company_rag.py backend/main.py backend/tests/test_company_rag.py
git commit -m "feat(company-rag): add company-rag router (list/upload/delete)"
```

---

## Task 6: Allow company members to download company docs

**Files:**
- Modify: `backend/routers/documents.py` (`get_signed_download_url` ~line 868; `proxy_download_document` ~line 949)

- [ ] **Step 1: Update the access check in `get_signed_download_url`**

The current check (~lines 868-873) denies non-owners when there is no `agent_id`. Company docs have `agent_id=NULL` and `user_id=<uploader>`, so members would be wrongly blocked. Replace:

```python
        # Owner or has access to the agent
        if document.user_id != int(user_id):
            if document.agent_id:
                _user_can_access_agent(int(user_id), document.agent_id, db)
            else:
                raise HTTPException(status_code=403, detail="Access denied")
```

with:

```python
        # Owner, same-company member (for company RAG docs), or agent access
        if document.user_id != int(user_id):
            if getattr(document, "is_company_rag", False) and document.company_id:
                caller_cid = db.query(User.company_id).filter(User.id == int(user_id)).scalar()
                if caller_cid != document.company_id:
                    raise HTTPException(status_code=403, detail="Access denied")
            elif document.agent_id:
                _user_can_access_agent(int(user_id), document.agent_id, db)
            else:
                raise HTTPException(status_code=403, detail="Access denied")
```

Ensure `User` is imported in `documents.py` (it imports from `database`; add `User` if missing).

- [ ] **Step 2: Apply the same guard to `proxy_download_document`**

`proxy_download_document` (~line 949) performs an equivalent access check. Apply the identical company-doc branch there so the proxy-download fallback also allows same-company members.

- [ ] **Step 3: Write the test**

Append to `backend/tests/test_company_rag.py`:

```python
@pytest.mark.asyncio
async def test_member_can_get_download_url_for_company_doc(client, member_cookies, db_session, test_company, test_admin_user, mock_gcs):
    from tests.factories import DocumentFactory
    doc = DocumentFactory.build(
        user_id=test_admin_user.id, agent_id=None, company_id=test_company.id,
        is_company_rag=True, filename="shared.pdf",
        gcs_url="https://storage.googleapis.com/test-bucket/shared.pdf",
    )
    db_session.add(doc)
    db_session.flush()
    # test_admin_user and member share test_company
    resp = await client.get(f"/documents/{doc.id}/download-url", cookies=member_cookies)
    assert resp.status_code in (200, 502)  # 200 with signed/proxy url; never 403
    assert resp.status_code != 403
```

(Use `test_member_user`/`member_cookies` and `test_admin_user` which are both in `test_company`.)

- [ ] **Step 4: Run the test**

Run: `cd backend && python -m pytest tests/test_company_rag.py -k "download_url" -v`
Expected: PASS (or SKIP without PG).

- [ ] **Step 5: Commit**

```bash
git add backend/routers/documents.py backend/tests/test_company_rag.py
git commit -m "feat(company-rag): allow same-company members to download company docs"
```

---

## Task 7: Frontend — agent inclusion toggle

**Files:**
- Modify: `frontend/pages/agents.js` (form state ~line 31; toggle render in modal near the other toggles ~lines 539-576; FormData build ~lines 631-678; edit-modal prefill)

- [ ] **Step 1: Add `include_company_rag` to the form state**

In the `useState` initializer for `form` (~line 31), add the field:

```javascript
  date_awareness_enabled: false,
  include_company_rag: false,
  enabled_plugins: []
```

- [ ] **Step 2: Render the toggle in the modal**

Next to the existing Date Awareness / Weekly Recap toggles (~line 558), add an emerald-accented toggle following the existing switch pattern:

```jsx
<div className="flex items-start justify-between gap-4 py-3">
  <div>
    <p className="text-sm font-semibold text-gray-800">{t('agents:companyRag.label')}</p>
    <p className="text-xs text-gray-500">{t('agents:companyRag.help')}</p>
  </div>
  <button
    type="button"
    className={`w-14 h-7 flex items-center rounded-full px-1 transition-colors duration-200 focus:outline-none border border-emerald-600 ${form.include_company_rag ? 'bg-emerald-600' : 'bg-gray-200'}`}
    onClick={() => setForm(f => ({ ...f, include_company_rag: !f.include_company_rag }))}
  >
    <span className={`h-5 w-5 rounded-full shadow transition-transform duration-200 ${form.include_company_rag ? 'bg-white translate-x-7' : 'bg-gray-400 translate-x-0'}`} />
  </button>
</div>
```

- [ ] **Step 3: Send it in the FormData (create AND edit)**

In the FormData build (~line 631, near `formData.append("date_awareness_enabled", ...)`), add:

```javascript
formData.append("date_awareness_enabled", form.date_awareness_enabled ? "true" : "false");
formData.append("include_company_rag", form.include_company_rag ? "true" : "false");
```

Do this for both the create and the update code paths (search for every `formData.append("date_awareness_enabled"` occurrence and add the line beside each).

- [ ] **Step 4: Prefill on edit**

Where the edit modal hydrates `form` from a fetched agent (search for `date_awareness_enabled:` being read off the agent into `setForm`), add:

```javascript
  date_awareness_enabled: agent.date_awareness_enabled || false,
  include_company_rag: agent.include_company_rag || false,
```

- [ ] **Step 5: Lint the frontend**

Run: `cd frontend && npm run lint`
Expected: no new errors for `agents.js`.

- [ ] **Step 6: Commit**

```bash
git add frontend/pages/agents.js
git commit -m "feat(company-rag): add 'include company RAG' toggle to agent modal"
```

---

## Task 8: Frontend — "RAG Entreprise" section on the Organisation page

**Files:**
- Modify: `frontend/pages/organization.js` (add a section card; role is already known on the page as `membership.role` / similar)

- [ ] **Step 1: Add state and loaders near the other section state**

Add React state for the company docs and upload progress:

```javascript
const [companyDocs, setCompanyDocs] = useState([]);
const [companyDocsLoading, setCompanyDocsLoading] = useState(false);
const [companyDocUploading, setCompanyDocUploading] = useState(false);
```

Add a loader and call it from the page's data-loading effect (alongside how other sections load):

```javascript
const loadCompanyDocs = async () => {
  try {
    setCompanyDocsLoading(true);
    const res = await api.get('/api/company-rag/documents');
    setCompanyDocs(res.data.documents || []);
  } catch {
    showToast(t('organization:companyRag.loadError'), 'error');
  } finally {
    setCompanyDocsLoading(false);
  }
};
```

- [ ] **Step 2: Add upload + delete handlers**

```javascript
const handleCompanyDocUpload = async (e) => {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    setCompanyDocUploading(true);
    await api.post('/api/company-rag/documents', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    showToast(t('organization:companyRag.uploadSuccess'), 'success');
    await loadCompanyDocs();
  } catch (err) {
    showToast(err?.response?.data?.detail || t('organization:companyRag.uploadError'), 'error');
  } finally {
    setCompanyDocUploading(false);
    e.target.value = '';
  }
};

const handleCompanyDocDelete = async (docId) => {
  try {
    await api.delete(`/api/company-rag/documents/${docId}`);
    setCompanyDocs(docs => docs.filter(d => d.id !== docId));
  } catch {
    showToast(t('organization:companyRag.deleteError'), 'error');
  }
};
```

(Reuse whatever toast helper the page already uses — match the existing `showToast` signature in `organization.js`.)

- [ ] **Step 3: Render the section card**

Add a card consistent with the Integrations / Slash Commands sections. `canManage` is true for owner/admin (reuse the page's existing role variable, e.g. `['owner','admin'].includes(role)`):

```jsx
<section className="bg-white rounded-card border border-gray-200 p-6 mb-6">
  <div className="flex items-center justify-between mb-4">
    <h2 className="font-heading font-bold text-lg text-slate-900">{t('organization:companyRag.title')}</h2>
    {canManage && (
      <label className={`px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-button text-sm font-semibold cursor-pointer ${companyDocUploading ? 'opacity-60 pointer-events-none' : ''}`}>
        {companyDocUploading ? t('organization:companyRag.uploading') : t('organization:companyRag.upload')}
        <input type="file" className="hidden" accept=".pdf,.txt,.docx,.ics,.json" onChange={handleCompanyDocUpload} />
      </label>
    )}
  </div>
  <p className="text-sm text-gray-500 mb-4">{t('organization:companyRag.description')}</p>

  {companyDocsLoading ? (
    <p className="text-sm text-gray-400">{t('common:loading')}</p>
  ) : companyDocs.length === 0 ? (
    <p className="text-sm text-gray-400">{t('organization:companyRag.empty')}</p>
  ) : (
    <ul className="divide-y divide-gray-100">
      {companyDocs.map(doc => (
        <li key={doc.id} className="flex items-center justify-between py-3">
          <div className="min-w-0">
            <p className="text-sm font-medium text-gray-800 truncate">{doc.filename}</p>
            <p className="text-xs text-gray-400">{doc.created_at ? new Date(doc.created_at).toLocaleDateString() : ''}</p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <a href={`/_api/documents/${doc.id}/download`} className="text-xs text-primary-600 hover:underline">{t('organization:companyRag.download')}</a>
            {canManage && (
              <button onClick={() => handleCompanyDocDelete(doc.id)} className="text-xs text-red-600 hover:underline">
                {t('organization:companyRag.delete')}
              </button>
            )}
          </div>
        </li>
      ))}
    </ul>
  )}
</section>
```

Place this section inside the same page container as the existing Integrations/Slash-Commands sections so spacing matches. Confirm the download link base — the page's `api` instance uses `baseURL = '/_api'`, so a plain anchor should point to `/_api/documents/{id}/download` (or use the page's existing download helper if one exists, e.g. the same `download-url` flow as `sources/[agentId].js`; prefer reusing that helper if present).

- [ ] **Step 4: Lint the frontend**

Run: `cd frontend && npm run lint`
Expected: no new errors for `organization.js`.

- [ ] **Step 5: Commit**

```bash
git add frontend/pages/organization.js
git commit -m "feat(company-rag): add RAG Entreprise section to Organisation page"
```

---

## Task 9: i18n keys

**Files:**
- Modify: `frontend/public/locales/fr/organization.json`, `frontend/public/locales/en/organization.json`
- Modify: `frontend/public/locales/fr/agents.json`, `frontend/public/locales/en/agents.json`

- [ ] **Step 1: Add the `companyRag` block to organization (FR)**

In `frontend/public/locales/fr/organization.json`, add a top-level `"companyRag"` object:

```json
"companyRag": {
  "title": "RAG Entreprise",
  "description": "Documents partagés de l'organisation. Chaque companion peut choisir de les inclure dans sa base de connaissances.",
  "upload": "Ajouter un document",
  "uploading": "Envoi…",
  "empty": "Aucun document d'entreprise pour le moment.",
  "download": "Télécharger",
  "delete": "Supprimer",
  "uploadSuccess": "Document ajouté au RAG entreprise.",
  "uploadError": "Échec de l'envoi du document.",
  "deleteError": "Échec de la suppression.",
  "loadError": "Impossible de charger les documents d'entreprise."
}
```

- [ ] **Step 2: Add the `companyRag` block to organization (EN)**

In `frontend/public/locales/en/organization.json`:

```json
"companyRag": {
  "title": "Company RAG",
  "description": "Shared organization documents. Each companion can choose to include them in its knowledge base.",
  "upload": "Add a document",
  "uploading": "Uploading…",
  "empty": "No company documents yet.",
  "download": "Download",
  "delete": "Delete",
  "uploadSuccess": "Document added to the company RAG.",
  "uploadError": "Document upload failed.",
  "deleteError": "Deletion failed.",
  "loadError": "Could not load company documents."
}
```

- [ ] **Step 3: Add the `companyRag` block to agents (FR + EN)**

In `frontend/public/locales/fr/agents.json`:

```json
"companyRag": {
  "label": "Inclure le RAG entreprise",
  "help": "Donne à ce companion accès aux documents partagés de l'entreprise."
}
```

In `frontend/public/locales/en/agents.json`:

```json
"companyRag": {
  "label": "Include company RAG",
  "help": "Gives this companion access to the organization's shared documents."
}
```

(Insert each block as a sibling key — validate the JSON stays well-formed, e.g. with `python -c "import json; json.load(open(p))"` for each file.)

- [ ] **Step 4: Validate JSON + lint**

Run:
```bash
cd frontend && node -e "['fr','en'].forEach(l=>['organization','agents'].forEach(n=>require('./public/locales/'+l+'/'+n+'.json')))" && npm run lint
```
Expected: no JSON parse errors, no new lint errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/public/locales
git commit -m "feat(company-rag): add i18n keys for company RAG section and toggle"
```

---

## Task 10: Full verification

- [ ] **Step 1: Backend tests**

Run: `cd backend && python -m pytest tests/test_company_rag.py tests/test_endpoints_agents.py tests/test_rag_engine.py tests/test_endpoints_documents.py -v`
Expected: PASS or SKIP (no failures).

- [ ] **Step 2: Backend lint**

Run: `cd backend && python -m ruff check .`
Expected: no errors in changed files.

- [ ] **Step 3: Frontend build**

Run: `cd frontend && npm run lint && npm run build`
Expected: lint clean, build succeeds.

- [ ] **Step 4: Manual end-to-end (requires running stack)**

1. As org owner, open Organisation → RAG Entreprise → upload a `.txt` whose content answers a specific question. Confirm it lists and downloads.
2. Create an agent with the toggle OFF. Ask the question → answer must NOT use the company doc.
3. Edit the agent, turn the toggle ON, save. Ask again → answer now uses the company doc.
4. Open that agent's per-agent Sources page → the company doc must NOT appear there.
5. Log in as a member → Organisation shows the company doc list read-only (no upload/delete), and download works.

- [ ] **Step 5: Final commit (if any verification fixups were needed)**

```bash
git add -A
git commit -m "chore(company-rag): verification fixups"
```

---

## Self-Review notes (author)

- **Spec coverage:** data model (Task 1), retrieval default-exclude + opt-in union + personal-scope leak guard (Task 3), owner/admin-only management + member read (Tasks 5/6 via `require_role`), agent toggle (Tasks 4/7), Organisation section (Task 8), i18n (Task 9), migration via `ensure_columns` (Task 1), tests (Tasks 1/3/4/5/6). All spec sections map to a task.
- **Naming consistency:** `is_company_rag` (Document) and `include_company_rag` (Agent) used identically across model, migrations, ingestion, retrieval, endpoints, serialization, and frontend form keys.
- **Known integration checks flagged inline:** exact `app.include_router` style in `main.py` (Task 5 Step 4); `MAX_FILE_SIZE`/`event_tracker` import origins (Task 5 Step 3); the page's existing role variable + toast helper + download helper in `organization.js` (Task 8); every `date_awareness_enabled` FormData occurrence in `agents.js` (Task 7 Step 3).
