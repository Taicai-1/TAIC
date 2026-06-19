# RAG Entreprise — Design Spec

**Date:** 2026-06-15
**Branch (base):** `feature/missions` → new feature branch
**Status:** Approved for planning

## Goal

Let an organization maintain a shared "company RAG" — a set of documents owned by the company rather than any single agent — and let each companion/agent **opt in** to including that shared knowledge in its own RAG via a single toggle.

Two user-facing surfaces:
1. **Organisation page** gains a "RAG Entreprise" section to upload / list / delete company documents (owner & admin only; members see a read-only list).
2. **Agent create/edit modal** gains an "Inclure le RAG entreprise" toggle (all-or-nothing).

## Decisions (locked)

- **Permissions:** only org **owner + admin** can add/delete company RAG documents. Any member can enable the toggle on their own agents and read the company document list.
- **Inclusion mode:** single boolean toggle per agent (all company docs or none). No per-document selection.

## Non-goals (YAGNI)

- No per-document selection for inclusion.
- No company-doc versioning or scheduled refresh beyond what URL documents already support.
- No new top-level navigation entry — the section lives inside the existing Organisation page.
- No team/sub-organization scoping.

## Data model

Two boolean columns, following the existing toggle convention (cf. `date_awareness_enabled`).

| Table | Column | Definition | Meaning |
|-------|--------|-----------|---------|
| `documents` | `is_company_rag` | `BOOLEAN NOT NULL DEFAULT FALSE` | Marks a document as company-shared. Such rows have `company_id=<org>`, `agent_id=NULL`, `mission_id=NULL`, `user_id=<uploader>`. |
| `agents` | `include_company_rag` | `BOOLEAN NOT NULL DEFAULT FALSE` | Per-agent opt-in to pull company docs into retrieval. |

**Migration mechanism:** append both rows to the `migrations` list in `backend/database.py` (`ensure_columns`, ~line 1011–1016) — the same `ADD COLUMN IF NOT EXISTS` path used for `date_awareness_enabled` and `documents.mission_id`. Also add the fields to the SQLAlchemy `Document` and `Agent` models so `create_all` covers fresh DBs. No Alembic revision required (inline ensure-step is the established precedent for additive boolean columns).

Company documents reuse the **entire** existing ingestion pipeline unchanged: `process_document_for_user` → `ingest_text_content` → `DocumentChunk.embedding_vec` (pgvector 1024). Chunks already carry `company_id`, so tenant isolation and RLS apply automatically.

## Retrieval — `backend/rag_engine.py`

### `search_similar_texts_for_user(...)`
Add parameter `include_company_rag: bool = False`. Company docs are **excluded by default** and **unioned in only when the agent opts in**. The existing hard `company_id` filter on both `Document` and `DocumentChunk` is untouched, so cross-org leakage remains impossible.

```python
# agent-scoped branch
elif agent_id:
    agent_scope = and_(Document.agent_id == agent_id, Document.mission_id.is_(None))
    if include_company_rag:
        query = query.filter(or_(agent_scope, Document.is_company_rag.is_(True)))
    else:
        query = query.filter(agent_scope, Document.is_company_rag.is_(False))

# personal user-scoped branch — never leak company docs into personal RAG
else:
    query = query.filter(
        Document.user_id == user_id,
        Document.mission_id.is_(None),
        Document.is_company_rag.is_(False),
    )
```

(The `is_company_rag.is_(False)` on the user branch is required: a company doc uploaded by user X has `user_id=X` and `mission_id=NULL`, so without it the doc would leak into X's personal RAG.)

Ensure `and_`, `or_` are imported from SQLAlchemy in `rag_engine.py`.

### `get_answer(...)`
- Read `agent.include_company_rag` (via `getattr(agent, "include_company_rag", False)`) and pass it to `search_similar_texts_for_user(include_company_rag=...)`.
- When building the "available documents" list injected into the system prompt for an agent, also include company documents (`is_company_rag=True`, same `company_id`) when the toggle is on, so the model is aware of them. Mirror the existing doc-list query with the same union logic.

## Backend API — new `backend/routers/company_rag.py`

Company is derived from `current_user.company_id` (no id in the path). Every handler enforces same-company; write handlers additionally require role ∈ {owner, admin} (reuse the existing org-role check used by `organization.js` endpoints / `permissions.py`).

| Method | Path | Auth | Behaviour |
|--------|------|------|-----------|
| GET | `/api/company-rag/documents` | any member | List company docs: `id`, `filename`, `source_url`, `document_type`/source badge, `created_at`. |
| POST | `/api/company-rag/documents` | owner/admin | Multipart upload. Reuses the `/upload-agent` flow but sets `is_company_rag=True`, `agent_id=None`, `company_id=current_user.company_id`. Async via Redis BackgroundTasks when available, sync fallback. Returns `{filename, document_id|task_id, status}`. |
| DELETE | `/api/company-rag/documents/{id}` | owner/admin | Verify the doc belongs to the caller's company and `is_company_rag=True`; delete doc (chunks cascade). |
| GET | `/api/company-rag/documents/{id}/download` | any member | Reuse the existing GCS download handler/pattern. |

Register the router in `main.py` alongside the other routers. Reuse the same file-validation (extension, size, content-type) as `/upload-agent`.

### Agent endpoints (`backend/routers/agents.py`)
- POST `/api/agents` and PUT `/api/agents/{id}`: add `include_company_rag: str = Form("false")`, parsed with `.lower() in ("true", "1", "yes")` (same as `neo4j_enabled`).
- Add `include_company_rag` to the agent GET serialization.

## Frontend

### `pages/organization.js` — "RAG Entreprise" section
A new card consistent with the Integrations / Slash Commands sections:
- Upload control (hidden `<input type="file">` in a styled label, multipart via `api.post('/api/company-rag/documents', formData, { headers: { 'Content-Type': 'multipart/form-data' } })`). When Redis-async, poll status like the agent upload flow.
- Document list reusing the `sources/[agentId].js` row style: filename / source badge (PDF, DOCX, URL…), created date, download button, delete button.
- Upload + delete controls render only when `role ∈ {owner, admin}` (the page already knows the role); members get a read-only list.
- Loading / empty / error states with toasts, matching the page's existing patterns.

### `pages/agents.js` — inclusion toggle
- Add `include_company_rag: false` to the `form` state.
- Render the existing switch component (new accent color, emerald) labelled "Inclure le RAG entreprise" with short help text ("Donne à ce companion accès aux documents partagés de l'entreprise.").
- Append to `FormData`: `formData.append("include_company_rag", form.include_company_rag ? "true" : "false")` on both create and edit.
- Prefill from the agent object when opening the edit modal.

### i18n
Add FR keys (and EN if the namespace has an EN file) to the `organization` and `agents` namespaces for: section title, upload button, empty state, delete confirm, toggle label, help text.

## Testing

DB-free unit tests (consistent with the existing `backend/tests/` suite):
- `include_company_rag` form-string parsing → bool (true/false/1/0/missing).
- Agent serialization includes `include_company_rag`.
- A small extracted pure helper that, given `(agent_id, include_company_rag)`, returns the intended scope predicate description / branch selection — unit-tested without a DB.

Manual verification (retrieval requires Postgres + pgvector):
1. As owner, upload a company doc on the Organisation page; confirm it lists and downloads.
2. Create an agent with the toggle OFF → ask a question only answerable from the company doc → answer should NOT use it.
3. Flip the toggle ON → same question → answer now uses the company doc.
4. Confirm the company doc does not appear in the agent's per-agent Sources page, nor in personal RAG.
5. As a member, confirm read-only list (no upload/delete).

## Files touched (anticipated)

**Backend**
- `database.py` — model fields on `Document`/`Agent` + two `migrations` rows.
- `rag_engine.py` — `search_similar_texts_for_user` param + scope filters; `get_answer` wiring + available-docs list.
- `routers/company_rag.py` — new router.
- `routers/agents.py` — form param + serialization.
- `main.py` — register router.
- `tests/` — new unit tests.

**Frontend**
- `pages/organization.js` — RAG Entreprise section.
- `pages/agents.js` — toggle + form wiring.
- `public/locales/**/organization.json`, `agents.json` — i18n keys.
