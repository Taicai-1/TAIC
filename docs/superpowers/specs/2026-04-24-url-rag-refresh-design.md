# URL RAG Source with Refresh — Design Spec

## Goal

Allow users to add a website URL as a RAG document source for an agent, store the source URL, and manually refresh (re-fetch + re-embed) the content when needed.

## Current State

- `POST /upload-url` already fetches a URL, extracts HTML content, chunks it, and creates a `Document` with embeddings
- The source URL is **not stored** on the `Document` model — once ingested, there's no way to know which document came from a URL
- No refresh capability exists
- Frontend sources page (`/sources/[agentId]`) displays documents but has no URL-specific UI

## Changes

### 1. Database: Add `source_url` to Document

**File:** `backend/database.py`

Add a nullable column to the `Document` model:

```python
source_url = Column(String(2048), nullable=True)
```

**Migration file:** `backend/migrations/006_add_document_source_url.sql`

```sql
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_url VARCHAR(2048);
```

No index needed — we won't query by `source_url`, only read it when displaying documents.

### 2. Backend: Store URL on upload

**File:** `backend/routers/documents.py` — `upload_url()` endpoint

After `process_document_for_user()` returns the `doc_id`, update the document's `source_url`:

```python
doc = db.query(Document).filter(Document.id == doc_id).first()
doc.source_url = request.url
db.commit()
```

### 3. Backend: New refresh endpoint

**File:** `backend/routers/documents.py`

New endpoint `POST /documents/{document_id}/refresh-url`:

1. Load the `Document` by ID, verify ownership (`user_id` match or `AgentShare` with `can_edit`)
2. Verify `source_url` is not null (otherwise 400)
3. Re-fetch the URL using the same logic as `upload_url` (headers, SSRF protection, retry, HTML parsing)
4. Delete all existing `DocumentChunk` rows for this document
5. Re-chunk and re-embed the new content (reuse `ingest_text_content` logic but update in-place)
6. Update `Document.content` with the new text
7. Return `{"document_id", "status": "refreshed", "source_url"}`

To avoid code duplication, extract the URL-fetching + HTML-parsing logic from `upload_url` into a helper function `_fetch_and_parse_url(url: str) -> str` that returns cleaned text content.

### 4. Backend: Expose `source_url` in API responses

**File:** `backend/routers/sources.py` — `get_agent_sources()` endpoint

Add `source_url` to the document serialization in the response:

```python
"source_url": d.source_url,
```

**File:** `backend/routers/documents.py` — `get_user_documents()` endpoint

Add `source_url` to the response dict:

```python
"source_url": doc.source_url,
```

### 5. Frontend: URL management in sources page

**File:** `frontend/pages/sources/[agentId].js`

**Add URL input section** (visible only if user has edit permission — needs `can_edit` from API):
- Text input for URL + "Add" button
- On submit: `POST /upload-url` with `{ url, agent_id }`
- Show loading state during fetch

**Modify document list** to distinguish URL-sourced documents:
- If `doc.source_url` exists: show a link/globe icon instead of file icon, display the URL, show a "Refresh" button
- Refresh button: `POST /documents/{id}/refresh-url`, show spinner during refresh, toast on success/error

**Add `can_edit` to the API response** (`get_agent_sources`): already returns documents with `has_file`, just needs `source_url` added. The `can_edit` flag needs to be included in the response so the frontend knows whether to show add/refresh controls.

### 6. Translations

**File:** `frontend/public/locales/fr/sources.json` and `en/sources.json`

Add keys for:
- URL input placeholder
- Add URL button label
- Refresh button label
- Toast messages (success, error)
- "URL source" badge label

## Data Flow

```
Add URL:
  Input URL → POST /upload-url → fetch HTML → parse → chunk → embed
  → Document(source_url=url) + DocumentChunks created

Refresh URL:
  Click Refresh → POST /documents/{id}/refresh-url
  → re-fetch same URL → delete old chunks → re-chunk → re-embed
  → Document.content updated, new DocumentChunks created
```

## Error Handling

- URL unreachable: return 400 with user-friendly message (already handled in `upload_url`)
- Empty content after parsing: return 400
- Refresh on non-URL document: return 400 "This document has no source URL"
- Permission denied: return 403

## Not in scope

- Automatic/scheduled refresh (can be added later)
- Changing the source URL of an existing document (user can delete and re-add)
- Crawling multiple pages from a site (single URL only)
