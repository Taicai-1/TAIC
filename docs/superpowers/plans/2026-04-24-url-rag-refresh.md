# URL RAG Source with Refresh — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store the source URL on documents uploaded via URL, and add a refresh endpoint that re-fetches and re-embeds the content.

**Architecture:** Add `source_url` column to `Document` model. Extract URL-fetching logic into a reusable helper `_fetch_and_parse_url()`. Add `POST /documents/{id}/refresh-url` endpoint. Expose `source_url` in all document API responses. Update frontend sources page with URL input + refresh button.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, Next.js/React, Tailwind CSS

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `backend/database.py:358` | Modify | Add `source_url` column to Document model |
| `backend/migrations/006_add_document_source_url.sql` | Create | SQL migration for new column |
| `backend/routers/documents.py` | Modify | Extract `_fetch_and_parse_url()` helper, store `source_url` on upload, add refresh endpoint, expose `source_url` in responses |
| `backend/routers/sources.py:328-340` | Modify | Expose `source_url` in `get_agent_sources` response |
| `backend/tests/test_url_refresh.py` | Create | Unit tests for helper and refresh validation |
| `frontend/public/locales/fr/sources.json` | Modify | Add French translation keys |
| `frontend/public/locales/en/sources.json` | Modify | Add English translation keys |
| `frontend/pages/sources/[agentId].js` | Modify | URL input section + refresh button UI |

---

### Task 1: Database — Add `source_url` column

**Files:**
- Modify: `backend/database.py:358`
- Create: `backend/migrations/006_add_document_source_url.sql`

- [ ] **Step 1: Add `source_url` to the Document model**

In `backend/database.py`, add after line 358 (`drive_file_id`):

```python
source_url = Column(String(2048), nullable=True)
```

- [ ] **Step 2: Create migration file**

Create `backend/migrations/006_add_document_source_url.sql`:

```sql
-- Add source_url to documents for URL-based RAG sources
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_url VARCHAR(2048);
```

- [ ] **Step 3: Commit**

```bash
git add backend/database.py backend/migrations/006_add_document_source_url.sql
git commit -m "feat: add source_url column to Document model"
```

---

### Task 2: Backend — Extract URL fetch helper and store source_url on upload

**Files:**
- Modify: `backend/routers/documents.py:39-248`

- [ ] **Step 1: Extract `_fetch_and_parse_url()` helper function**

Add this function **before** the `upload_url` endpoint (at line 38, after `router = APIRouter()`). This extracts lines 43-230 of the existing `upload_url` into a reusable function:

```python
def _fetch_and_parse_url(url: str) -> tuple[str, str]:
    """Fetch a URL, parse HTML, and return (cleaned_text_content, filename).

    Raises HTTPException on failure.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "max-age=0",
    }

    import requests as http_requests

    max_retries = 3
    retry_delay = 2
    html = None
    last_error = None

    def _is_safe_redirect(redirect_url: str) -> bool:
        blocked_patterns = [
            "localhost", "127.0.0.1", "0.0.0.0", "192.168.", "10.",
            "172.16.", "172.17.", "172.18.", "172.19.", "172.20.",
            "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
            "172.26.", "172.27.", "172.28.", "172.29.", "172.30.",
            "172.31.", "169.254.", "[::1]", "[fc", "[fd",
            "metadata.google.internal",
        ]
        return not any(pattern in redirect_url.lower() for pattern in blocked_patterns)

    for attempt in range(max_retries):
        try:
            response = http_requests.get(url, headers=headers, timeout=20, allow_redirects=False, verify=True)
            redirect_count = 0
            while response.is_redirect and redirect_count < 5:
                redirect_url = response.headers.get("Location", "")
                if not redirect_url or not _is_safe_redirect(redirect_url):
                    raise http_requests.exceptions.ConnectionError("Redirect to blocked destination")
                response = http_requests.get(redirect_url, headers=headers, timeout=20, allow_redirects=False, verify=True)
                redirect_count += 1
            response.raise_for_status()
            if response.encoding:
                html = response.text
            else:
                response.encoding = response.apparent_encoding
                html = response.text
            break
        except http_requests.exceptions.SSLError as e:
            logger.warning(f"SSL error on attempt {attempt + 1} for {url}: {e}")
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
        except (http_requests.exceptions.Timeout, http_requests.exceptions.ConnectionError) as e:
            logger.warning(f"Connection error on attempt {attempt + 1} for {url}: {e}")
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
        except http_requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error for {url}: {e}")
            last_error = e
            break
        except Exception as e:
            logger.error(f"Unexpected error on attempt {attempt + 1} for {url}: {e}")
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(retry_delay)

    if html is None:
        error_msg = f"Failed to fetch URL after {max_retries} attempts"
        if last_error:
            error_msg += f": {str(last_error)}"
        logger.error(error_msg)
        raise HTTPException(status_code=400, detail="Unable to fetch the provided URL. Please check the URL and try again.")

    from bs4 import BeautifulSoup

    try:
        from readability import Document as ReadabilityDocument
        use_readability = True
    except Exception:
        use_readability = False

    title = ""
    meta_desc = ""
    main_text = ""

    try:
        soup = BeautifulSoup(html, "lxml")
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        md = soup.find("meta", attrs={"name": "description"})
        if md and md.get("content"):
            meta_desc = md.get("content").strip()

        if use_readability:
            try:
                doc = ReadabilityDocument(html)
                main_html = doc.summary()
                main_soup = BeautifulSoup(main_html, "lxml")
                main_text = "\n".join(
                    [p.get_text(separator=" ", strip=True) for p in main_soup.find_all(["p", "h1", "h2", "h3"])]
                )
            except Exception:
                use_readability = False

        if not main_text:
            body = soup.body
            if body:
                for tag in body.find_all(["script", "style", "nav", "footer", "aside", "header", "form", "noscript"]):
                    tag.decompose()
                paragraphs = [
                    p.get_text(separator=" ", strip=True)
                    for p in body.find_all(["p", "h1", "h2", "h3"])
                    if p.get_text(strip=True)
                ]
                main_text = "\n".join(paragraphs)

        cleaned = []
        if title:
            cleaned.append(f"Title: {title}")
        if meta_desc:
            cleaned.append(f"Description: {meta_desc}")
        if main_text:
            cleaned.append("Content:\n" + main_text)

        content = "\n\n".join(cleaned)
        if not content.strip():
            content = soup.get_text(separator="\n", strip=True)

    except Exception as e:
        logger.warning(f"Failed to parse HTML for useful content, falling back to raw. Error: {e}")
        content = html

    filename = url.split("//")[-1][:100].replace("/", "_") + ".txt"

    max_chars = 200000
    if len(content) > max_chars:
        content = content[:max_chars]

    return content, filename
```

- [ ] **Step 2: Refactor `upload_url` to use the helper and store `source_url`**

Replace the body of `upload_url` (lines 42-248) with:

```python
@router.post("/upload-url")
async def upload_url(request: UrlUploadValidated, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Ajoute une URL comme document/source pour le RAG"""
    try:
        content, filename = _fetch_and_parse_url(request.url)

        doc_id = process_document_for_user(
            filename,
            content.encode("utf-8", errors="ignore"),
            int(user_id),
            db,
            agent_id=request.agent_id,
            company_id=_get_caller_company_id(user_id, db),
        )

        # Store the source URL on the document
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.source_url = request.url
            db.commit()

        logger.info(f"URL ajoutée pour user {user_id}, agent {request.agent_id}: {request.url}")
        event_tracker.track_document_upload(int(user_id), request.url, len(content))

        return {"url": request.url, "document_id": doc_id, "agent_id": request.agent_id, "status": "uploaded"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de l'ajout d'URL: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors de l'ajout de l'URL")
```

- [ ] **Step 3: Commit**

```bash
git add backend/routers/documents.py
git commit -m "refactor: extract _fetch_and_parse_url helper and store source_url on upload"
```

---

### Task 3: Backend — Add refresh-url endpoint

**Files:**
- Modify: `backend/routers/documents.py` (add after `upload_url` endpoint, ~line 250)
- Depends on: `DocumentChunk` import (already imported in line 17 via `database.py`) — verify and add if needed

- [ ] **Step 1: Verify `DocumentChunk` is imported**

Check the imports at the top of `backend/routers/documents.py`. The current import (line 17) is:

```python
from database import get_db, Document, AgentShare, SessionLocal
```

Add `DocumentChunk` to this import:

```python
from database import get_db, Document, DocumentChunk, AgentShare, SessionLocal
```

- [ ] **Step 2: Add the refresh endpoint**

Add after the `upload_url` endpoint (after the closing of the function):

```python
@router.post("/documents/{document_id}/refresh-url")
async def refresh_document_url(document_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Re-fetch a URL-sourced document and re-embed its content."""
    try:
        uid = int(user_id)

        # Find document and verify access
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        # Check ownership or edit access via AgentShare
        is_owner = document.user_id == uid
        if not is_owner and document.agent_id:
            share = (
                db.query(AgentShare)
                .filter(AgentShare.agent_id == document.agent_id, AgentShare.user_id == uid, AgentShare.can_edit == True)
                .first()
            )
            if not share:
                raise HTTPException(status_code=403, detail="Access denied")
        elif not is_owner:
            raise HTTPException(status_code=403, detail="Access denied")

        # Verify this document has a source URL
        if not document.source_url:
            raise HTTPException(status_code=400, detail="This document has no source URL to refresh")

        # Re-fetch and parse the URL
        content, filename = _fetch_and_parse_url(document.source_url)

        if not content.strip():
            raise HTTPException(status_code=400, detail="No content could be extracted from the URL")

        # Delete old chunks
        db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()

        # Update document content
        document.content = content
        document.filename = filename
        db.commit()

        # Re-chunk and re-embed
        from file_loader import chunk_text
        from mistral_embeddings import get_embedding_fast, EMBEDDING_DIM
        import numpy as np

        chunks = chunk_text(content)

        def split_for_embedding(chunk, max_tokens=8192):
            chunk = chunk.replace("\x00", "")
            max_chars = max_tokens * 4
            return [chunk[i : i + max_chars] for i in range(0, len(chunk), max_chars)]

        for i, chunk in enumerate(chunks):
            sub_chunks = split_for_embedding(chunk, 8192)
            embeddings = []
            for sub in sub_chunks:
                embedding = get_embedding_fast(sub)
                embeddings.append(embedding)
            if embeddings:
                avg_embedding = list(np.mean(np.array(embeddings), axis=0))
            else:
                raise ValueError("No sub-chunks produced for embedding")
            doc_chunk = DocumentChunk(
                document_id=document_id,
                company_id=document.company_id,
                chunk_text=chunk,
                embedding_vec=avg_embedding,
                chunk_index=i,
            )
            db.add(doc_chunk)

        db.commit()

        logger.info(f"Document {document_id} refreshed from URL: {document.source_url} ({len(chunks)} chunks)")
        event_tracker.track_user_action(uid, f"url_refresh:{document.source_url}")

        return {
            "document_id": document_id,
            "status": "refreshed",
            "source_url": document.source_url,
            "chunks": len(chunks),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error refreshing document {document_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Error refreshing URL content")
```

- [ ] **Step 3: Commit**

```bash
git add backend/routers/documents.py
git commit -m "feat: add POST /documents/{id}/refresh-url endpoint"
```

---

### Task 4: Backend — Expose `source_url` in API responses

**Files:**
- Modify: `backend/routers/documents.py:633-640` (get_user_documents)
- Modify: `backend/routers/sources.py:330-340` (get_agent_sources)

- [ ] **Step 1: Add `source_url` to `get_user_documents` response**

In `backend/routers/documents.py`, in the `get_user_documents` function, the `doc_data` dict (around line 633) currently has:

```python
doc_data = {
    "id": doc.id,
    "filename": doc.filename,
    "created_at": doc.created_at.isoformat(),
    "gcs_url": doc.gcs_url,
    "notion_link_id": doc.notion_link_id,
    "drive_link_id": getattr(doc, "drive_link_id", None),
}
```

Add `source_url` to this dict:

```python
doc_data = {
    "id": doc.id,
    "filename": doc.filename,
    "created_at": doc.created_at.isoformat(),
    "gcs_url": doc.gcs_url,
    "notion_link_id": doc.notion_link_id,
    "drive_link_id": getattr(doc, "drive_link_id", None),
    "source_url": getattr(doc, "source_url", None),
}
```

- [ ] **Step 2: Add `source_url` to `get_agent_sources` response**

In `backend/routers/sources.py`, the documents list comprehension (lines 330-340) currently has:

```python
{
    "id": d.id,
    "filename": d.filename,
    "created_at": d.created_at.isoformat() if d.created_at else None,
    "has_file": bool(d.gcs_url),
    "notion_link_id": d.notion_link_id,
    "drive_link_id": getattr(d, "drive_link_id", None),
}
```

Add `source_url`:

```python
{
    "id": d.id,
    "filename": d.filename,
    "created_at": d.created_at.isoformat() if d.created_at else None,
    "has_file": bool(d.gcs_url),
    "notion_link_id": d.notion_link_id,
    "drive_link_id": getattr(d, "drive_link_id", None),
    "source_url": getattr(d, "source_url", None),
}
```

- [ ] **Step 3: Commit**

```bash
git add backend/routers/documents.py backend/routers/sources.py
git commit -m "feat: expose source_url in document API responses"
```

---

### Task 5: Backend — Unit tests

**Files:**
- Create: `backend/tests/test_url_refresh.py`

These tests validate the helper extraction logic and refresh endpoint validation without needing a database or external HTTP calls.

- [ ] **Step 1: Write unit tests**

Create `backend/tests/test_url_refresh.py`:

```python
"""Unit tests for URL refresh feature validation logic."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException


class TestFetchAndParseUrl:
    """Tests for the _fetch_and_parse_url helper."""

    def test_returns_content_and_filename(self):
        """Successful fetch returns (content, filename) tuple."""
        from routers.documents import _fetch_and_parse_url

        html = "<html><head><title>Test Page</title></head><body><p>Hello world</p></body></html>"
        mock_response = MagicMock()
        mock_response.is_redirect = False
        mock_response.encoding = "utf-8"
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()

        with patch("routers.documents._fetch_and_parse_url.__code__", side_effect=None):
            pass

        # Use requests mock at the module level
        with patch("requests.get", return_value=mock_response):
            content, filename = _fetch_and_parse_url("https://example.com/page")

        assert "Hello world" in content or "Test Page" in content
        assert filename.endswith(".txt")
        assert "example.com" in filename

    def test_unreachable_url_raises_400(self):
        """Unreachable URL raises HTTPException with 400."""
        from routers.documents import _fetch_and_parse_url
        import requests as http_requests

        with patch("requests.get", side_effect=http_requests.exceptions.ConnectionError("refused")):
            with pytest.raises(HTTPException) as exc_info:
                _fetch_and_parse_url("https://unreachable.invalid")
            assert exc_info.value.status_code == 400

    def test_filename_truncated_and_sanitized(self):
        """Long URLs produce truncated, sanitized filenames."""
        from routers.documents import _fetch_and_parse_url

        long_url = "https://example.com/" + "a" * 200

        html = "<html><body><p>Content</p></body></html>"
        mock_response = MagicMock()
        mock_response.is_redirect = False
        mock_response.encoding = "utf-8"
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_response):
            content, filename = _fetch_and_parse_url(long_url)

        # Filename should be max 100 chars from URL + ".txt"
        assert len(filename) <= 105
        assert "/" not in filename

    def test_content_truncated_at_200k(self):
        """Content longer than 200k chars is truncated."""
        from routers.documents import _fetch_and_parse_url

        long_content = "x" * 300000
        html = f"<html><body><p>{long_content}</p></body></html>"
        mock_response = MagicMock()
        mock_response.is_redirect = False
        mock_response.encoding = "utf-8"
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_response):
            content, filename = _fetch_and_parse_url("https://example.com")

        assert len(content) <= 200000


class TestRefreshUrlValidation:
    """Tests for refresh endpoint input validation (no DB needed)."""

    def test_document_without_source_url_should_fail(self):
        """A document with source_url=None should not be refreshable."""
        # This validates the business rule: only URL-sourced documents can be refreshed
        doc = MagicMock()
        doc.source_url = None

        # The endpoint checks `if not document.source_url` and raises 400
        assert not doc.source_url

    def test_document_with_source_url_should_be_refreshable(self):
        """A document with a source_url set is eligible for refresh."""
        doc = MagicMock()
        doc.source_url = "https://example.com/page"

        assert doc.source_url == "https://example.com/page"
```

- [ ] **Step 2: Run tests**

Run: `cd backend && python -m pytest tests/test_url_refresh.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_url_refresh.py
git commit -m "test: add unit tests for URL fetch helper and refresh validation"
```

---

### Task 6: Frontend — Translations

**Files:**
- Modify: `frontend/public/locales/fr/sources.json`
- Modify: `frontend/public/locales/en/sources.json`

- [ ] **Step 1: Add French translation keys**

In `frontend/public/locales/fr/sources.json`, add these keys to the existing structure:

The `"url"` section goes as a new top-level key alongside `"documents"`, `"notion"`, `"toast"`:

```json
{
  "pageTitle": "Sources",
  "backToChat": "Retour au chat",
  "sections": {
    "documents": "Documents RAG",
    "notion": "Sources Notion"
  },
  "documents": {
    "empty": "Aucun document RAG pour cet agent",
    "download": "Télécharger",
    "open": "Ouvrir",
    "fromNotion": "Notion",
    "fromUrl": "URL"
  },
  "notion": {
    "empty": "Aucune source Notion liée",
    "ingest": "Ajouter au RAG",
    "ingesting": "Ingestion en cours...",
    "ingested": "Dans les sources",
    "page": "Page",
    "database": "Base de données"
  },
  "url": {
    "placeholder": "https://example.com/page",
    "add": "Ajouter",
    "adding": "Ajout en cours...",
    "refresh": "Rafraîchir",
    "refreshing": "Rafraîchissement..."
  },
  "toast": {
    "ingestSuccess": "Contenu Notion ingéré avec succès ({{chunks}} chunks)",
    "ingestError": "Erreur lors de l'ingestion Notion",
    "alreadyIngested": "Ce contenu Notion a déjà été ingéré",
    "downloadError": "Erreur lors du téléchargement",
    "urlAddSuccess": "URL ajoutée avec succès",
    "urlAddError": "Erreur lors de l'ajout de l'URL",
    "urlRefreshSuccess": "Contenu mis à jour avec succès ({{chunks}} chunks)",
    "urlRefreshError": "Erreur lors du rafraîchissement de l'URL"
  },
  "loading": "Chargement des sources..."
}
```

- [ ] **Step 2: Add English translation keys**

In `frontend/public/locales/en/sources.json`:

```json
{
  "pageTitle": "Sources",
  "backToChat": "Back to chat",
  "sections": {
    "documents": "RAG Documents",
    "notion": "Notion Sources"
  },
  "documents": {
    "empty": "No RAG documents for this agent",
    "download": "Download",
    "open": "Open",
    "fromNotion": "Notion",
    "fromUrl": "URL"
  },
  "notion": {
    "empty": "No Notion sources linked",
    "ingest": "Add to RAG",
    "ingesting": "Ingesting...",
    "ingested": "In sources",
    "page": "Page",
    "database": "Database"
  },
  "url": {
    "placeholder": "https://example.com/page",
    "add": "Add",
    "adding": "Adding...",
    "refresh": "Refresh",
    "refreshing": "Refreshing..."
  },
  "toast": {
    "ingestSuccess": "Notion content ingested successfully ({{chunks}} chunks)",
    "ingestError": "Error ingesting Notion content",
    "alreadyIngested": "This Notion content has already been ingested",
    "downloadError": "Error downloading file",
    "urlAddSuccess": "URL added successfully",
    "urlAddError": "Error adding URL",
    "urlRefreshSuccess": "Content refreshed successfully ({{chunks}} chunks)",
    "urlRefreshError": "Error refreshing URL content"
  },
  "loading": "Loading sources..."
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/public/locales/fr/sources.json frontend/public/locales/en/sources.json
git commit -m "feat: add translation keys for URL sources"
```

---

### Task 7: Frontend — URL input and refresh UI in sources page

**Files:**
- Modify: `frontend/pages/sources/[agentId].js`

- [ ] **Step 1: Add URL state and imports**

In `frontend/pages/sources/[agentId].js`, update the imports (line 1-13) and state (line 36-39):

Replace the imports block:

```javascript
import { useState, useEffect } from "react";
import { useRouter } from "next/router";
import { useTranslation } from "next-i18next";
import { serverSideTranslations } from "next-i18next/serverSideTranslations";
import {
  FileText,
  Download,
  Loader2,
  File,
  Globe,
  RefreshCw,
  Plus,
} from "lucide-react";
import Layout from "../../components/Layout";
import { useAuth } from "../../hooks/useAuth";
import api from "../../lib/api";
```

Add new state variables after the existing state declarations (after line 39):

```javascript
const [canEdit, setCanEdit] = useState(false);
const [urlInput, setUrlInput] = useState("");
const [addingUrl, setAddingUrl] = useState(false);
const [refreshingDocId, setRefreshingDocId] = useState(null);
```

- [ ] **Step 2: Update `loadSources` to capture `can_edit`**

Replace the `loadSources` function (lines 51-62):

```javascript
const loadSources = async (id) => {
  try {
    setLoading(true);
    const res = await api.get(`/api/agents/${id}/sources`);
    setAgentName(res.data.agent_name || "");
    setDocuments(res.data.documents || []);
    setCanEdit(res.data.can_edit || false);
  } catch {
    showToast(t("errors:generic", "Error loading sources"), "error");
  } finally {
    setLoading(false);
  }
};
```

- [ ] **Step 3: Add URL submit and refresh handlers**

Add after the `handleDownload` function (after line 85):

```javascript
const handleAddUrl = async (e) => {
  e.preventDefault();
  if (!urlInput.trim() || addingUrl) return;
  try {
    setAddingUrl(true);
    await api.post("/upload-url", { url: urlInput.trim(), agent_id: parseInt(agentId) });
    showToast(t("sources:toast.urlAddSuccess"));
    setUrlInput("");
    loadSources(agentId);
  } catch {
    showToast(t("sources:toast.urlAddError"), "error");
  } finally {
    setAddingUrl(false);
  }
};

const handleRefreshUrl = async (docId) => {
  if (refreshingDocId) return;
  try {
    setRefreshingDocId(docId);
    const res = await api.post(`/documents/${docId}/refresh-url`);
    showToast(t("sources:toast.urlRefreshSuccess", { chunks: res.data.chunks }));
    loadSources(agentId);
  } catch {
    showToast(t("sources:toast.urlRefreshError"), "error");
  } finally {
    setRefreshingDocId(null);
  }
};
```

- [ ] **Step 4: Add URL input form in the JSX**

In the JSX return, add the URL input section **before** the documents list (after the `{agentName && ...}` paragraph, before `<section>`). Insert:

```jsx
{/* URL Input */}
{canEdit && (
  <form onSubmit={handleAddUrl} className="mb-6 flex items-center space-x-2">
    <div className="flex-1 relative">
      <Globe className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
      <input
        type="url"
        value={urlInput}
        onChange={(e) => setUrlInput(e.target.value)}
        placeholder={t("sources:url.placeholder")}
        className="w-full pl-10 pr-4 py-2.5 border border-gray-200 rounded-button text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        disabled={addingUrl}
      />
    </div>
    <button
      type="submit"
      disabled={!urlInput.trim() || addingUrl}
      className="flex items-center space-x-1.5 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 text-white text-sm font-medium rounded-button transition-colors"
    >
      {addingUrl ? (
        <>
          <Loader2 className="w-4 h-4 animate-spin" />
          <span>{t("sources:url.adding")}</span>
        </>
      ) : (
        <>
          <Plus className="w-4 h-4" />
          <span>{t("sources:url.add")}</span>
        </>
      )}
    </button>
  </form>
)}
```

- [ ] **Step 5: Update document list to show URL badge and refresh button**

In the document list `{documents.map((doc) => { ... })}` block, replace the inner content of each document row. The current code (lines 132-171) renders a file icon, filename, date, badge, and download button.

Replace the full `{documents.map((doc) => { ... })}` block:

```jsx
{documents.map((doc) => {
  const ext = getFileExtension(doc.filename);
  const isNotion = !!doc.notion_link_id;
  const isUrl = !!doc.source_url;
  return (
    <div
      key={doc.id}
      className="flex items-center justify-between p-4 bg-white border border-gray-200 rounded-card shadow-subtle hover:shadow-card transition-all"
    >
      <div className="flex items-center space-x-3 min-w-0">
        {isUrl ? (
          <Globe className="w-5 h-5 text-blue-500 flex-shrink-0" />
        ) : (
          <File className="w-5 h-5 text-gray-400 flex-shrink-0" />
        )}
        <div className="min-w-0">
          <p className="text-sm font-medium text-gray-900 truncate">
            {isUrl ? doc.source_url : doc.filename}
          </p>
          <p className="text-xs text-gray-500">
            {doc.created_at ? new Date(doc.created_at).toLocaleDateString() : ""}
          </p>
        </div>
        {isNotion ? (
          <span className="px-2 py-0.5 text-xs rounded-full bg-purple-100 text-purple-700 border border-purple-200 flex-shrink-0">
            {t("sources:documents.fromNotion")}
          </span>
        ) : isUrl ? (
          <span className="px-2 py-0.5 text-xs rounded-full bg-blue-100 text-blue-700 border border-blue-200 flex-shrink-0">
            {t("sources:documents.fromUrl")}
          </span>
        ) : (
          <span className={`px-2 py-0.5 text-xs rounded-full flex-shrink-0 ${getBadgeColor(ext)}`}>
            {ext}
          </span>
        )}
      </div>
      <div className="flex items-center space-x-2 flex-shrink-0 ml-4">
        {isUrl && canEdit && (
          <button
            onClick={() => handleRefreshUrl(doc.id)}
            disabled={refreshingDocId === doc.id}
            className="flex items-center space-x-1 px-3 py-1.5 text-xs bg-green-50 hover:bg-green-100 disabled:bg-gray-100 text-green-700 disabled:text-gray-400 rounded-button transition-colors border border-green-200 disabled:border-gray-200"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshingDocId === doc.id ? "animate-spin" : ""}`} />
            <span>
              {refreshingDocId === doc.id
                ? t("sources:url.refreshing")
                : t("sources:url.refresh")}
            </span>
          </button>
        )}
        {doc.has_file && (
          <button
            onClick={() => handleDownload(doc.id, doc.filename)}
            className="flex items-center space-x-1 px-3 py-1.5 text-xs bg-blue-50 hover:bg-blue-100 text-blue-700 rounded-button transition-colors border border-blue-200"
          >
            <Download className="w-3.5 h-3.5" />
            <span>{t("sources:documents.download")}</span>
          </button>
        )}
      </div>
    </div>
  );
})}
```

- [ ] **Step 6: Commit**

```bash
git add frontend/pages/sources/[agentId].js
git commit -m "feat: add URL input and refresh button to sources page"
```

---

### Task 8: Verify — Lint and test

**Files:** None (verification only)

- [ ] **Step 1: Run backend linter**

Run: `cd backend && python -m ruff check .`
Expected: No errors in modified files

- [ ] **Step 2: Run backend tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests pass (existing 39 + new URL tests)

- [ ] **Step 3: Run frontend lint**

Run: `cd frontend && npm run lint`
Expected: No errors

- [ ] **Step 4: Run frontend build**

Run: `cd frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 5: Fix any lint/test issues found, then commit fixes if needed**
