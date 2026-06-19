# WS5 — Robustness Essentials + Smoke Test Implementation Plan

> Execute task-by-task (superpowers:executing-plans). Only the REAL gaps — much robustness is already in place.

**Goal:** Remove the remaining ways a single request can hang a worker, OOM the process, or accept abusive input — then a manual end-to-end smoke pass on the client's flows.

**Already OK (verified, no work):** OpenAI/Gemini/Notion timeouts + OpenAI retries; prod error handler hides stack traces (no redundant middleware); `/upload` full file validation; `create_team` uses `TeamCreateV2Validated`.

---

## Task 1 (CODE): Mistral timeout

**File:** `backend/mistral_client.py`. The `timeout` param is declared but never passed → a slow/hung Mistral call blocks indefinitely.

- [ ] **Step 1:** Pass `timeout_ms`/`timeout` to each `client.chat.complete(...)` / `client.chat.stream(...)` call. The Mistral SDK accepts `timeout_ms` (milliseconds) on the request. Read the exact call sites (~lines 96, 158, 211) and add `timeout_ms=timeout * 1000` (the function param `timeout` is in seconds). If the installed SDK signature doesn't accept it, wrap the call so it can't hang (document the SDK version checked).
- [ ] **Step 2:** Verify import; run mistral-related tests (mocked). Commit `fix(reliability): enforce request timeout on Mistral client calls`.

---

## Task 2 (CODE): Pagination caps on high-volume list endpoints

**Files:** `routers/conversations.py` (list convos ~62-76, messages ~108), `routers/documents.py` (user documents ~798), `routers/company_rag.py` (documents ~58).

**Why:** these grow unbounded per user/org; `.all()` can OOM / slow on a large account. Add a bounded `limit` (default 100, max 500) + `skip` offset, newest-first. Keep returning a JSON list so the frontend keeps working (it just gets the most recent N). Full cursor UI = backlog.

- [ ] **Step 1:** For each endpoint add query params:

```python
from fastapi import Query
...
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
```
and apply `.order_by(<created/timestamp>.desc()).offset(skip).limit(limit)` to the query (conversations already order by created_at desc; messages order by timestamp — keep asc but still cap with limit; for messages use `.limit(limit)` taking the most recent then the existing asc ordering, or document the choice).

- [ ] **Step 2:** Run the endpoint tests (`test_endpoints_conversations.py`, `test_endpoints_documents.py`, `test_company_rag.py`) — they should still pass (small fixtures < limit). Commit `feat(reliability): bounded pagination on conversations/messages/documents/company-rag list endpoints`.

> Note in the commit: default 100 / max 500; with a brand-new client this never truncates real data; a paginated frontend is backlog.

---

## Task 3 (CODE): Input length bounds on agent create/update + folder name

**Files:** `routers/agents.py` (`create_agent` ~196-303, `update_agent` ~742-764), `routers/company_rag.py` (folder create ~241-269, rename ~272-306). `validation.py` already defines `MAX_AGENT_NAME_LENGTH=200`, `MAX_AGENT_CONTEXTE_LENGTH=10000`, `MAX_AGENT_BIOGRAPHIE_LENGTH=5000` and `sanitize_text`.

- [ ] **Step 1:** In `create_agent`/`update_agent`, after reading the Form fields, bound the free-text ones using the existing constants + `sanitize_text` (which trims, strips null bytes, enforces max). E.g.:

```python
from validation import sanitize_text, MAX_AGENT_NAME_LENGTH, MAX_AGENT_CONTEXTE_LENGTH, MAX_AGENT_BIOGRAPHIE_LENGTH

name = sanitize_text(name, MAX_AGENT_NAME_LENGTH)
contexte = sanitize_text(contexte, MAX_AGENT_CONTEXTE_LENGTH) if contexte else contexte
biographie = sanitize_text(biographie, MAX_AGENT_BIOGRAPHIE_LENGTH) if biographie else biographie
```
(Confirm `sanitize_text`'s exact signature first; it may be `sanitize_text(value, max_length)`.) Reject empty `name` with 422 if it becomes empty after sanitize.

- [ ] **Step 2:** For folder create/rename, bound the name (e.g. `MAX_FOLDER_NAME_LENGTH = 100`): if `len(name) > 100`, raise 400; keep the existing empty-name 400.
- [ ] **Step 3:** Run agent + company-rag-folder tests. Commit `feat(security): bound agent + folder text input lengths`.

---

## Task 4 (CODE): company-rag upload validation parity

**File:** `routers/company_rag.py` upload (~80-151). `/upload` (documents.py) already validates magic bytes + PDF pages; mirror it here.

- [ ] **Step 1:** After the extension check, add `validate_file_content(content, file.filename)` (import from `validation`) and the same PDF page-count pre-check used in `documents.py` (reuse `MAX_PDF_PAGES`). Raise the same 400/413 errors on failure, BEFORE `process_document_for_user`.
- [ ] **Step 2:** Run company-rag tests. Commit `fix(security): validate file content + PDF page count on company-rag upload`.

---

## Task 5 (DOC): End-to-end smoke-test checklist

**File:** Create `docs/ops/launch-smoke-test.md`. Manual checklist to run on dev (then prod with a test account) before onboarding — the last gate before the launch release.

- [ ] **Step 1:** Write the checklist covering the client's real flows: signup → email verify → login → 2FA setup (capture backup codes) → login with TOTP → login with a backup code → create agent → upload each doc type (pdf/txt/docx) → ask a RAG question → company-RAG upload into a folder → ask using company docs → share an agent with an org member → conversation history → missions/recap if used → logout. For each: expected result + what a failure looks like. Include the cap/limit checks (over-cap → 429) and the rollback command reference.
- [ ] **Step 2:** Commit `docs(ops): launch smoke-test checklist`.

---

## Definition of Done
- Mistral calls can't hang (timeout passed).
- List endpoints bounded (no unbounded `.all()` on high-volume tables).
- Agent/folder text inputs length-bounded; company-rag upload validates content.
- Full suite green in CI.
- Smoke-test checklist written (executed by owner before launch).

## Self-review
- Skips everything already-OK (OpenAI/Gemini/Notion timeouts, error handler, /upload validation, team validation).
- Pagination keeps a list response → no frontend break; truncation only matters at >limit items (backlog: paginated UI).
- Smoke test is manual by nature (needs a running app); delivered as a checklist.
