# Test Coverage Expansion Design

**Date:** 2026-04-28
**Goal:** Reach 70%+ backend test coverage (currently ~39 unit tests only)

## Current State

- 6 test files: auth, validation, company_request, drive, url_refresh
- No endpoint tests, no RAG tests, no integration tests
- CI runs `pytest tests/ -v` with no DB, no coverage reporting
- conftest.py sets env vars only (JWT_SECRET_KEY, DATABASE_URL=sqlite, ENVIRONMENT=test)

## Design

### 1. CI Infrastructure

Add PostgreSQL 15 service container to the `test-backend` GitHub Actions job:

```yaml
services:
  postgres:
    image: postgres:15
    env:
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
      POSTGRES_DB: taic_test
    ports:
      - 5432:5432
    options: >-
      --health-cmd pg_isready
      --health-interval 10s
      --health-timeout 5s
      --health-retries 5
```

Environment variable `DATABASE_URL=postgresql://test:test@localhost:5432/taic_test` passed to pytest.

Add `pytest-cov` to run coverage with `--cov=. --cov-report=term-missing --cov-fail-under=70`.

### 2. New Dev Dependencies

Add to `requirements-dev.txt`:
- `pytest-cov` - coverage reporting and threshold enforcement
- `fakeredis` - in-memory Redis mock for cache tests
- `factory-boy` - model factories for clean test data creation

### 3. Test Fixtures

#### conftest.py (major rewrite)

The root conftest.py becomes the test infrastructure hub:

- **`engine` / `test_db` (session scope):** Create all tables at session start, drop at end. Uses the real PostgreSQL from CI services.
- **`db_session` (function scope):** Opens a transaction, yields the session, rolls back after each test. Fast isolation without recreating tables.
- **`client` (function scope):** `httpx.AsyncClient` with `ASGITransport(app=app)`. Overrides the `get_db` dependency with the test session.
- **`test_user` (function scope):** Creates a user in the DB, returns the User object.
- **`auth_headers` (function scope):** Returns `{"Cookie": "access_token=<valid_jwt>"}` for authenticated requests.
- **`test_agent` (function scope):** Creates an agent owned by `test_user`.
- **`mock_openai` / `mock_mistral` / `mock_gemini`:** Patch LLM client functions to return deterministic responses.
- **`mock_redis`:** Patch `get_redis()` to return a `fakeredis` instance.

#### Test file fixtures

```
backend/tests/fixtures/
  sample.pdf      - 1-page PDF with known text content
  sample.docx     - Simple DOCX with known paragraphs
  sample.pptx     - Simple PPTX with known slide text
  embeddings.json - Pre-computed embedding vectors (dim=1536) for 5 test chunks
```

### 4. Test Modules

#### 4a. Endpoint Tests (real DB, test client)

**`test_endpoints_auth.py`**
- POST `/auth/signup` - success, duplicate email, weak password
- POST `/auth/login` - success, wrong password, nonexistent user
- GET `/auth/verify` - valid token, expired token, no token
- 2FA setup and verification flow
- ~12 tests

**`test_endpoints_agents.py`**
- POST `/agents` - create agent with various settings
- GET `/agents` - list user's agents, verify isolation
- GET `/agents/{id}` - get by ID, 404, access control
- PUT `/agents/{id}` - update settings, name, LLM provider
- DELETE `/agents/{id}` - delete, verify cascade
- Agent sharing (AgentShare model)
- ~15 tests

**`test_endpoints_ask.py`**
- POST `/ask` - basic query with mocked LLM, returns response
- POST `/ask` - with conversation context (follow-up)
- POST `/ask` - agent not found, unauthorized
- POST `/ask` - empty query, validation errors
- Verify RAG retrieval is called with correct parameters (mocked)
- ~8 tests

**`test_endpoints_documents.py`**
- POST `/upload-agent` - upload PDF, DOCX, TXT (multipart)
- Verify document and chunks created in DB
- GET `/agents/{id}/documents` - list documents
- DELETE `/documents/{id}` - delete document and chunks
- File validation (size, type)
- ~10 tests

**`test_endpoints_conversations.py`**
- GET `/conversations` - list for user
- GET `/conversations/{id}` - get with messages
- POST `/conversations` - create new
- DELETE `/conversations/{id}` - delete
- Verify conversation belongs to correct user (isolation)
- ~8 tests

#### 4b. RAG Engine Tests (mocked embeddings)

**`test_rag_engine.py`**
- `chunk_text()` - verify chunk sizes, overlap, edge cases (empty, very short, very long)
- `get_embeddings()` - mocked, verify correct provider called based on agent config
- `retrieve_relevant_chunks()` - with pre-computed embeddings in fixtures, verify ranking
- `generate_response()` - mocked LLM, verify prompt construction with context
- Cache hit/miss behavior (mocked Redis)
- ~15 tests

#### 4c. File Loader Tests (real test files)

**`test_file_loader.py`**
- `load_pdf()` - parse fixture PDF, verify extracted text
- `load_docx()` - parse fixture DOCX, verify paragraphs
- `load_pptx()` - parse fixture PPTX, verify slide text
- `load_web_content()` - mocked HTTP, verify HTML parsing
- Error handling: corrupt file, empty file, unsupported format
- ~10 tests

#### 4d. Integration Tests (fully mocked external APIs)

**`test_integrations_slack.py`**
- Slack event webhook handling (message, app_mention)
- Slack bot configuration CRUD
- Message routing to correct agent
- Signature verification
- ~8 tests

**`test_integrations_notion.py`**
- Notion link creation and sync trigger
- Page content extraction (mocked Notion API)
- Sync error handling (API down, invalid token)
- ~6 tests

**`test_integrations_drive.py`** (extends existing `test_drive.py`)
- Drive link creation and sync trigger
- Folder content listing (mocked Drive API)
- File download and processing (mocked)
- ~6 tests

#### 4e. Supporting Tests

**`test_actions.py`**
- Action registration decorator
- Action execution with mocked Google Docs/Sheets APIs
- Invalid action handling
- ~6 tests

**`test_redis_cache.py`**
- Embedding cache get/set/TTL
- RAG cache with user scoping
- User profile cache and invalidation
- Graceful fallback when Redis unavailable (get_redis() returns None)
- ~8 tests

**`test_permissions.py`**
- Multi-tenant isolation: user A cannot access user B's agents/conversations
- Agent sharing: shared agent accessible by recipient
- Company membership access controls
- Public vs private agent access
- ~10 tests

### 5. Test Count Summary

| Category | File | Tests |
|----------|------|-------|
| Existing | test_auth, test_validation, test_company_request, test_drive, test_url_refresh | ~39 |
| Auth endpoints | test_endpoints_auth | ~12 |
| Agent endpoints | test_endpoints_agents | ~15 |
| Ask endpoints | test_endpoints_ask | ~8 |
| Document endpoints | test_endpoints_documents | ~10 |
| Conversation endpoints | test_endpoints_conversations | ~8 |
| RAG engine | test_rag_engine | ~15 |
| File loader | test_file_loader | ~10 |
| Slack | test_integrations_slack | ~8 |
| Notion | test_integrations_notion | ~6 |
| Drive | test_integrations_drive | ~6 |
| Actions | test_actions | ~6 |
| Redis cache | test_redis_cache | ~8 |
| Permissions | test_permissions | ~10 |
| **Total** | | **~161** |

### 6. CI Pipeline Changes

Updated `test-backend` job in `.github/workflows/ci.yml`:

1. Add `services.postgres` (PostgreSQL 15 container)
2. Set `DATABASE_URL` to point to the service
3. Add mock env vars for API keys (empty strings or test values)
4. Run pytest with coverage: `python -m pytest tests/ -v --tb=short --cov=. --cov-report=term-missing --cov-fail-under=70`
5. Existing tests continue to work (conftest.py backwards-compatible)

### 7. Implementation Order

1. Infrastructure first: requirements-dev.txt, conftest.py, CI config, fixture files
2. Endpoint tests (highest coverage impact): auth, agents, documents, conversations, ask
3. RAG engine + file loader tests
4. Integration tests: Slack, Notion, Drive
5. Supporting tests: actions, redis, permissions
6. Coverage verification and threshold tuning

### 8. Constraints

- All LLM API calls fully mocked - no real API keys needed in CI
- All external service calls (Slack, Notion, Drive, GCS) fully mocked
- PostgreSQL service container handles DB tests - no testcontainers dependency
- Existing 39 tests must continue passing unchanged
- fakeredis handles Redis tests - no Redis service container needed
- Test files (PDF, DOCX, PPTX) are minimal fixtures committed to the repo
