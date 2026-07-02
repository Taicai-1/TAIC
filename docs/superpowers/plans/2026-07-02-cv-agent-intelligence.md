# CV Agent Intelligence (Phases 2-4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a CV-base companion three real capabilities in chat — sourcing, analytics, and candidate Q&A — via an intent router that calls one of three read-only tools, layered on top of the existing RAG answer path with a clean fallback.

**Architecture:** A new `backend/cv_agent.py` holds the data-access layer over `candidate_profiles`, three tool JSON-schemas, an LLM intent router (`get_chat_response_with_tools`), and orchestrators (`answer_cv` / `answer_cv_stream`). `rag_engine.get_answer` / `get_answer_stream` call the orchestrator first **only** when the agent's company-RAG folders include a CV-base folder; if the router picks no tool or a tool errors, the orchestrator returns `None` and the normal RAG path runs unchanged.

**Tech Stack:** FastAPI / SQLAlchemy / PostgreSQL + pgvector, existing multi-provider LLM tool-calling (`openai_client.get_chat_response_with_tools`), Mistral embeddings, pytest (DB tests gated on real Postgres via the `db_session` fixture).

**Spec:** `docs/superpowers/specs/2026-07-02-cv-agent-intelligence-design.md`

---

## Conventions (verified — read before starting)

- **DB tests SKIP locally** (no `DATABASE_URL`); they run in CI against real Postgres. Verify locally: clean collection, pure tests pass, full suite has no NEW failures. `CompanyFolder.company_id` is **NOT NULL** — DB tests must use the `test_company` fixture (`test_user` has no company). See `tests/conftest.py`.
- **CI runs `ruff format --check .`** (stricter than `ruff check`). **Always run `python -m ruff format .` before committing.**
- Reuse `cv_extraction.normalize_skills` for skill normalization (do not reimplement).
- Existing signatures (verified):
  - `rag_engine.get_answer(question, user_id, db, selected_doc_ids=None, agent_id=None, history=None, model_id=None, company_id=None, use_rag=True, use_graph=True) -> dict` (rag_engine.py:249). Returns `{"answer", "sources", "graph_data", ...}`.
  - `rag_engine.get_answer_stream(...)` (rag_engine.py:556) — a generator yielding SSE strings; **read its exact signature/params before delegating**.
  - `rag_engine.search_similar_texts_for_user(query_embedding, user_id, db, top_k=3, selected_doc_ids=None, agent_id=None, company_id=None, mission_id=None, include_company_rag=False, company_rag_folder_ids=None, recap_schedule_id=None) -> list[dict]` (rag_engine.py:902). Each dict has `document_id`, `similarity`, `chunk_text`, `filename`.
  - `openai_client.get_chat_response_with_tools(messages, tools, model_id=None, gemini_only=False) -> ToolCallResponse` where `ToolCallResponse{content: str|None, tool_call: ToolCall|None}` and `ToolCall{name: str, arguments: dict, id: str}` — **arguments is an already-parsed dict** (openai_client.py:686-708). Tools are OpenAI format: `[{"type":"function","function":{"name","description","parameters"}}]`.
  - `openai_client.get_chat_response(messages, model_id=None, gemini_only=False) -> str` (openai_client.py:244) for phrasing.
  - `mistral_embeddings.get_embedding_fast(text) -> list[float]`.
  - `streaming_response.sse_event(event_type, data) -> str`.
  - `CandidateProfile` (database.py:673): `document_id, company_id, folder_id, full_name, current_title, location, seniority, years_experience, skills(JSONB), languages(JSONB), education_level, last_company, extraction_status`.

## File structure

| File | Responsibility | Create/Modify |
|---|---|---|
| `backend/cv_agent.py` | CV intelligence: activation check, data access, tool schemas, router, orchestrators | **Create** |
| `backend/rag_engine.py` | Inject the CV orchestrator at the top of `get_answer` / `get_answer_stream` | Modify |
| `backend/tests/test_cv_agent.py` | Unit tests (router/schemas/rank — no DB) + DB tests (data access, integration) | **Create** |

**Delivery order:** A (Tasks 1-4, foundation) → B (5-6, Q&A) → C (7-8, sourcing) → D (9-10, analytics).

---

## Task 1: Activation check — `folders_include_cv_base`

**Files:** Create `backend/cv_agent.py`; Test: `backend/tests/test_cv_agent.py`

- [ ] **Step 1: Write the failing DB test** (create `backend/tests/test_cv_agent.py`)

```python
import cv_agent
from database import CompanyFolder


def test_folders_include_cv_base(db_session, test_company):
    cv = CompanyFolder(company_id=test_company.id, name="CVs", is_cv_base=True)
    plain = CompanyFolder(company_id=test_company.id, name="Docs", is_cv_base=False)
    db_session.add_all([cv, plain])
    db_session.flush()

    assert cv_agent.folders_include_cv_base(db_session, test_company.id, [cv.id, plain.id]) is True
    assert cv_agent.folders_include_cv_base(db_session, test_company.id, [plain.id]) is False
    # folder_ids=None means "all company folders" → true because a cv_base exists
    assert cv_agent.folders_include_cv_base(db_session, test_company.id, None) is True
    # no company → false
    assert cv_agent.folders_include_cv_base(db_session, None, [cv.id]) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -v`
Expected: FAIL at collection — `ModuleNotFoundError: No module named 'cv_agent'` (or SKIP once the module exists but the function is missing → then AttributeError). If `DATABASE_URL` is unset the DB test SKIPS; that is the correct local outcome once the module imports cleanly.

- [ ] **Step 3: Write minimal implementation** (create `backend/cv_agent.py`)

```python
"""Conversational CV intelligence: intent router + three read-only tools
(sourcing / analytics / candidate Q&A) layered on top of the RAG answer path.

Activated only for companions whose company-RAG folders include a CV-base folder;
otherwise callers fall back to the normal RAG flow (answer_cv returns None)."""

import json
import logging

logger = logging.getLogger(__name__)


def folders_include_cv_base(db, company_id, folder_ids):
    """True if the company has a CV-base folder within ``folder_ids`` (or any, if None)."""
    if not company_id:
        return False
    from database import CompanyFolder

    q = db.query(CompanyFolder.id).filter(
        CompanyFolder.company_id == company_id,
        CompanyFolder.is_cv_base.is_(True),
    )
    if folder_ids:
        q = q.filter(CompanyFolder.id.in_(folder_ids))
    return bool(db.query(q.exists()).scalar())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -v`
Expected: the DB test SKIPS locally (no DB), no collection error. In CI it PASSES.

- [ ] **Step 5: Format + commit**

```bash
cd backend && python -m ruff format cv_agent.py tests/test_cv_agent.py && python -m ruff check cv_agent.py tests/test_cv_agent.py
git add backend/cv_agent.py backend/tests/test_cv_agent.py
git commit -m "feat(cv-agent): CV-base folder activation check"
```

---

## Task 2: Tool schemas + intent router — `route_cv_intent`

**Files:** Modify `backend/cv_agent.py`; Test: `backend/tests/test_cv_agent.py`

The router makes ONE `get_chat_response_with_tools` call exposing three tools and returns `(tool_name, args_dict)` or `None` when the LLM picks no tool.

- [ ] **Step 1: Write the failing unit test** (pure — mocks the LLM; no DB)

```python
import openai_client


def test_route_cv_intent_returns_tool(monkeypatch):
    from openai_client import ToolCall, ToolCallResponse

    def fake_tools(messages, tools, model_id=None, gemini_only=False):
        # Assert the three tools are offered.
        names = {t["function"]["name"] for t in tools}
        assert names == {"cv_sourcing", "cv_analytics", "cv_qa"}
        return ToolCallResponse(content=None, tool_call=ToolCall(name="cv_analytics", arguments={"metric": "count", "dimension": "skill"}))

    monkeypatch.setattr(cv_agent, "get_chat_response_with_tools", fake_tools)
    routed = cv_agent.route_cv_intent("Combien maîtrisent React ?", history=None, model_id="gpt-4o-mini")
    assert routed == ("cv_analytics", {"metric": "count", "dimension": "skill"})


def test_route_cv_intent_no_tool_returns_none(monkeypatch):
    from openai_client import ToolCallResponse

    monkeypatch.setattr(
        cv_agent, "get_chat_response_with_tools",
        lambda messages, tools, model_id=None, gemini_only=False: ToolCallResponse(content="hello", tool_call=None),
    )
    assert cv_agent.route_cv_intent("Bonjour", history=None, model_id=None) is None


def test_cv_tools_are_valid_openai_schema():
    for t in cv_agent.CV_TOOLS:
        assert t["type"] == "function"
        assert t["function"]["name"] in {"cv_sourcing", "cv_analytics", "cv_qa"}
        assert t["function"]["parameters"]["type"] == "object"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -k "route_cv_intent or cv_tools" -v`
Expected: FAIL — `AttributeError: module 'cv_agent' has no attribute 'CV_TOOLS'`.

- [ ] **Step 3: Write minimal implementation** (append to `backend/cv_agent.py`)

Add the import near the top (with the other imports):

```python
from openai_client import get_chat_response_with_tools, get_chat_response
```

Append:

```python
CV_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "cv_sourcing",
            "description": "Find and rank candidate CVs matching required skills / seniority / location. Use for 'find/trouve/cherche des candidats/profils qui ...'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skills": {"type": "array", "items": {"type": "string"}, "description": "Required skills, e.g. ['python','react']"},
                    "seniority": {"type": "string", "description": "junior|confirmé|senior|lead"},
                    "location": {"type": "string"},
                    "min_years": {"type": "integer"},
                    "free_text": {"type": "string", "description": "Free-text of the need / job offer for semantic ranking"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cv_analytics",
            "description": "Aggregate statistics over the CV base (counts, averages, distributions). Use for 'combien / how many / moyenne / répartition ...'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string", "enum": ["count", "avg_experience", "distribution"]},
                    "dimension": {"type": "string", "enum": ["skill", "seniority", "location", "language"]},
                    "filter": {
                        "type": "object",
                        "properties": {
                            "skill": {"type": "string"},
                            "seniority": {"type": "string"},
                            "location": {"type": "string"},
                            "min_years": {"type": "integer"},
                        },
                    },
                },
                "required": ["metric", "dimension"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cv_qa",
            "description": "Answer a question about ONE specific named candidate. Use for 'résume le parcours de X', 'quelles compétences a X'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_name": {"type": "string"},
                    "question": {"type": "string", "description": "The question to answer about the candidate"},
                },
                "required": ["candidate_name", "question"],
            },
        },
    },
]

_ROUTER_SYSTEM = (
    "You route a recruiter's message about a CV database to the right tool. "
    "Call cv_sourcing to find/rank candidates, cv_analytics for counts/averages/distributions, "
    "cv_qa for a question about one named candidate. "
    "If the message is small talk or unrelated to the CV base, DO NOT call any tool."
)


def route_cv_intent(question, history, model_id):
    """Return (tool_name, args_dict) chosen by the LLM, or None to fall back to normal RAG."""
    messages = [{"role": "system", "content": _ROUTER_SYSTEM}]
    for m in (history or [])[-6:]:
        role = m.get("role") if isinstance(m, dict) else None
        content = m.get("content") if isinstance(m, dict) else None
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})
    try:
        resp = get_chat_response_with_tools(messages, tools=CV_TOOLS, model_id=model_id)
    except Exception as e:
        logger.warning(f"cv route failed: {e}")
        return None
    if resp.tool_call is None:
        return None
    return resp.tool_call.name, (resp.tool_call.arguments or {})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -k "route_cv_intent or cv_tools" -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Format + commit**

```bash
cd backend && python -m ruff format cv_agent.py tests/test_cv_agent.py && python -m ruff check cv_agent.py tests/test_cv_agent.py
git add backend/cv_agent.py backend/tests/test_cv_agent.py
git commit -m "feat(cv-agent): tool schemas + LLM intent router"
```

---

## Task 3: Orchestrator `answer_cv` + inject into `get_answer`

**Files:** Modify `backend/cv_agent.py`, `backend/rag_engine.py:266-275`; Test: `backend/tests/test_cv_agent.py`

`answer_cv` dispatches to a per-tool handler and returns a dict shaped like `get_answer`'s output, or `None` to fall back. In this task only the dispatch + fallback exist; the three handlers are added in Tasks 6/8/10. Until then, unknown tools return `None` (fallback). A handler may return a `{"stream_doc_id", "question"}` marker asking the orchestrator to run targeted single-CV RAG (used by Q&A).

- [ ] **Step 1: Write the failing unit test** (pure — mock router + a fake handler)

```python
def test_answer_cv_dispatches_and_falls_back(monkeypatch):
    # No tool chosen -> None (fallback to RAG).
    monkeypatch.setattr(cv_agent, "route_cv_intent", lambda q, history, model_id: None)
    assert cv_agent.answer_cv("hi", 1, None, agent_id=2, history=None, model_id=None, company_id=5, folder_ids=[7]) is None

    # A tool chosen -> its handler result is returned.
    monkeypatch.setattr(cv_agent, "route_cv_intent", lambda q, history, model_id: ("cv_analytics", {"metric": "count", "dimension": "skill"}))
    monkeypatch.setattr(cv_agent, "_HANDLERS", {"cv_analytics": lambda args, ctx: {"answer": "42", "sources": []}})
    out = cv_agent.answer_cv("combien", 1, None, agent_id=2, history=None, model_id=None, company_id=5, folder_ids=[7])
    assert out == {"answer": "42", "sources": []}

    # Handler raises -> None (graceful fallback).
    def boom(args, ctx):
        raise RuntimeError("db down")

    monkeypatch.setattr(cv_agent, "_HANDLERS", {"cv_analytics": boom})
    assert cv_agent.answer_cv("combien", 1, None, agent_id=2, history=None, model_id=None, company_id=5, folder_ids=[7]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -k answer_cv_dispatches -v`
Expected: FAIL — `AttributeError: module 'cv_agent' has no attribute 'answer_cv'`.

- [ ] **Step 3: Write minimal implementation** (append to `backend/cv_agent.py`)

```python
class _CvContext:
    """Everything a tool handler needs, bundled so handlers share one signature."""

    def __init__(self, question, user_id, db, agent_id, history, model_id, company_id, folder_ids):
        self.question = question
        self.user_id = user_id
        self.db = db
        self.agent_id = agent_id
        self.history = history
        self.model_id = model_id
        self.company_id = company_id
        self.folder_ids = folder_ids


# Populated by later tasks: {"cv_qa": fn, "cv_sourcing": fn, "cv_analytics": fn}.
# Each handler has signature (args: dict, ctx: _CvContext) -> dict | None.
_HANDLERS = {}


def answer_cv(question, user_id, db, agent_id, history, model_id, company_id, folder_ids):
    """Route the message to a CV tool and return an answer dict, or None to fall back to RAG."""
    routed = route_cv_intent(question, history, model_id)
    if routed is None:
        return None
    name, args = routed
    handler = _HANDLERS.get(name)
    if handler is None:
        return None
    try:
        ctx = _CvContext(question, user_id, db, agent_id, history, model_id, company_id, folder_ids)
        result = handler(args, ctx)
        if not result:
            return None
        # A handler may ask the orchestrator to run targeted single-CV RAG (Q&A).
        if result.get("stream_doc_id"):
            import rag_engine

            return rag_engine.get_answer(
                result["question"], ctx.user_id, ctx.db,
                selected_doc_ids=[result["stream_doc_id"]], agent_id=ctx.agent_id,
                history=ctx.history, model_id=ctx.model_id, company_id=ctx.company_id,
            )
        return result
    except Exception as e:
        logger.warning(f"cv_agent handler '{name}' failed: {e}")
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -k answer_cv_dispatches -v`
Expected: PASS (1 test).

- [ ] **Step 5: Inject into `get_answer`** — in `backend/rag_engine.py`, immediately AFTER the line that expands folders (currently `company_rag_folder_ids = _expand_company_folder_ids(company_rag_folder_ids, company_scope_id, db)`, rag_engine.py:274), add:

```python
        # CV companion: if the agent's company-RAG folders include a CV base, let the CV
        # intent router try to answer (sourcing/analytics/Q&A). None -> fall back to RAG.
        # `not selected_doc_ids` prevents re-entry: the Q&A path re-calls get_answer with an
        # explicit selected_doc_ids, which must run plain targeted RAG (no re-routing).
        if include_company_rag and agent_id and not selected_doc_ids:
            import cv_agent

            if cv_agent.folders_include_cv_base(db, company_scope_id, company_rag_folder_ids):
                _cv = cv_agent.answer_cv(
                    question, user_id, db, agent_id, history, model_id, company_scope_id, company_rag_folder_ids
                )
                if _cv is not None:
                    return _cv
```

- [ ] **Step 6: Verify no regression + commit**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -q && python -m pytest -q`
Expected: pure tests pass; full suite has no NEW failures.

```bash
cd backend && python -m ruff format cv_agent.py rag_engine.py tests/test_cv_agent.py && python -m ruff check cv_agent.py rag_engine.py tests/test_cv_agent.py
git add backend/cv_agent.py backend/rag_engine.py backend/tests/test_cv_agent.py
git commit -m "feat(cv-agent): answer_cv orchestrator + inject into get_answer"
```

---

## Task 4: Streaming orchestrator `answer_cv_stream` + inject into `get_answer_stream`

**Files:** Modify `backend/cv_agent.py`, `backend/rag_engine.py` (`get_answer_stream`, ~556); Test: `backend/tests/test_cv_agent.py`

For streaming, compute the route/result up front (so any failure → `None` → RAG fallback), then return a generator that emits SSE events. Q&A that resolves to a single candidate delegates to `get_answer_stream` (real token streaming); sourcing/analytics/clarifications emit the finished text as one `token` event + a `done` event.

- [ ] **Step 1: Write the failing unit test** (pure)

```python
import json as _json


def test_answer_cv_stream_emits_sse(monkeypatch):
    monkeypatch.setattr(cv_agent, "route_cv_intent", lambda q, history, model_id: ("cv_analytics", {"metric": "count", "dimension": "skill"}))
    monkeypatch.setattr(cv_agent, "_HANDLERS", {"cv_analytics": lambda args, ctx: {"answer": "42 profils", "sources": []}})

    gen = cv_agent.answer_cv_stream("combien", 1, None, agent_id=2, history=None, model_id=None, company_id=5, folder_ids=[7])
    events = list(gen)
    blob = "".join(events)
    assert "42 profils" in blob
    assert "event: done" in blob


def test_answer_cv_stream_none_when_no_tool(monkeypatch):
    monkeypatch.setattr(cv_agent, "route_cv_intent", lambda q, history, model_id: None)
    assert cv_agent.answer_cv_stream("hi", 1, None, agent_id=2, history=None, model_id=None, company_id=5, folder_ids=[7]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -k answer_cv_stream -v`
Expected: FAIL — `AttributeError: module 'cv_agent' has no attribute 'answer_cv_stream'`.

- [ ] **Step 3: Write minimal implementation** (append to `backend/cv_agent.py`)

Add the import near the top:

```python
from streaming_response import sse_event
```

Append:

```python
def answer_cv_stream(question, user_id, db, agent_id, history, model_id, company_id, folder_ids):
    """Streaming variant. Returns an SSE generator, or None to fall back to RAG streaming.

    Q&A on a single resolved candidate delegates to rag_engine.get_answer_stream for real
    token streaming; everything else emits the finished text as one token + a done event.
    """
    routed = route_cv_intent(question, history, model_id)
    if routed is None:
        return None
    name, args = routed
    handler = _HANDLERS.get(name)
    if handler is None:
        return None
    try:
        ctx = _CvContext(question, user_id, db, agent_id, history, model_id, company_id, folder_ids)
        # cv_qa handlers may return a special dict {"stream_doc_id": <id>} to request delegation.
        result = handler(args, ctx)
    except Exception as e:
        logger.warning(f"cv_agent stream handler '{name}' failed: {e}")
        return None
    if not result:
        return None

    if result.get("stream_doc_id"):
        import rag_engine

        return rag_engine.get_answer_stream(
            result["question"], user_id, db,
            selected_doc_ids=[result["stream_doc_id"]],
            agent_id=agent_id, history=history, model_id=model_id, company_id=company_id,
        )

    def _gen():
        yield sse_event("token", {"t": result["answer"]})
        yield sse_event("done", {"full_text": result["answer"], "sources": result.get("sources", [])})

    return _gen()
```

Note: `get_answer_stream`'s real parameter list may differ — before writing the delegation call, open `rag_engine.py:556` and pass arguments matching its actual signature (keep `selected_doc_ids=[doc_id]`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -k answer_cv_stream -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Inject into `get_answer_stream`** — read `rag_engine.py:556` to find where it resolves `include_company_rag` / `company_rag_folder_ids` / `company_scope_id` (mirrors `get_answer`). Immediately after those are resolved and expanded, add:

```python
        if include_company_rag and agent_id and not selected_doc_ids:
            import cv_agent

            if cv_agent.folders_include_cv_base(db, company_scope_id, company_rag_folder_ids):
                _cv_stream = cv_agent.answer_cv_stream(
                    question, user_id, db, agent_id, history, model_id, company_scope_id, company_rag_folder_ids
                )
                if _cv_stream is not None:
                    yield from _cv_stream
                    return
```

`not selected_doc_ids` is required to prevent infinite re-entry: the Q&A path delegates to
`get_answer_stream` with an explicit `selected_doc_ids`, which must stream plain targeted RAG.
If `get_answer_stream` uses different local variable names for the resolved folder ids / company
id (or a different name than `selected_doc_ids`), adapt the call to those names (do not rename
existing variables).

- [ ] **Step 6: Verify + commit**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -q && python -m pytest -q`
Expected: pure tests pass; full suite no NEW failures.

```bash
cd backend && python -m ruff format cv_agent.py rag_engine.py tests/test_cv_agent.py && python -m ruff check cv_agent.py rag_engine.py tests/test_cv_agent.py
git add backend/cv_agent.py backend/rag_engine.py backend/tests/test_cv_agent.py
git commit -m "feat(cv-agent): streaming orchestrator + inject into get_answer_stream"
```

---

## Task 5: `find_candidate_by_name` (Phase 4 data access)

**Files:** Modify `backend/cv_agent.py`; Test: `backend/tests/test_cv_agent.py` (DB)

- [ ] **Step 1: Write the failing DB test**

```python
from database import CandidateProfile, Document


def _cv_doc_with_profile(db_session, test_company, folder_id, name):
    doc = Document(filename=f"{name}.pdf", content="x", user_id=1, company_id=test_company.id,
                   is_company_rag=True, folder_id=folder_id)
    db_session.add(doc)
    db_session.flush()
    prof = CandidateProfile(document_id=doc.id, company_id=test_company.id, folder_id=folder_id,
                            full_name=name, extraction_status="done")
    db_session.add(prof)
    db_session.flush()
    return doc


def test_find_candidate_by_name(db_session, test_company):
    folder = CompanyFolder(company_id=test_company.id, name="CVs", is_cv_base=True)
    db_session.add(folder)
    db_session.flush()
    _cv_doc_with_profile(db_session, test_company, folder.id, "Jean Dupont")
    _cv_doc_with_profile(db_session, test_company, folder.id, "Marie Martin")

    hits = cv_agent.find_candidate_by_name(db_session, test_company.id, [folder.id], "dupont")
    assert len(hits) == 1 and hits[0]["full_name"] == "Jean Dupont"
    assert cv_agent.find_candidate_by_name(db_session, test_company.id, [folder.id], "Nobody") == []
    # tenant isolation: other company sees nothing
    assert cv_agent.find_candidate_by_name(db_session, test_company.id + 999, [folder.id], "dupont") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -k find_candidate_by_name -v`
Expected: FAIL/SKIP — AttributeError (no `find_candidate_by_name`) at collection if DB present; SKIP locally after the function exists.

- [ ] **Step 3: Write minimal implementation** (append to `backend/cv_agent.py`)

```python
def find_candidate_by_name(db, company_id, folder_ids, name):
    """Return [{document_id, full_name}] whose full_name matches ``name`` (ILIKE), tenant-scoped."""
    from database import CandidateProfile

    if not company_id or not name or not name.strip():
        return []
    q = db.query(CandidateProfile.document_id, CandidateProfile.full_name).filter(
        CandidateProfile.company_id == company_id,
        CandidateProfile.full_name.ilike(f"%{name.strip()}%"),
        CandidateProfile.extraction_status == "done",
    )
    if folder_ids:
        q = q.filter(CandidateProfile.folder_id.in_(folder_ids))
    return [{"document_id": r[0], "full_name": r[1]} for r in q.limit(10).all()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -k find_candidate_by_name -v`
Expected: SKIP locally (no DB), no collection error. PASSES in CI.

- [ ] **Step 5: Format + commit**

```bash
cd backend && python -m ruff format cv_agent.py tests/test_cv_agent.py && python -m ruff check cv_agent.py tests/test_cv_agent.py
git add backend/cv_agent.py backend/tests/test_cv_agent.py
git commit -m "feat(cv-agent): find_candidate_by_name (Q&A data access)"
```

---

## Task 6: `cv_qa` handler + register (Phase 4 complete)

**Files:** Modify `backend/cv_agent.py`; Test: `backend/tests/test_cv_agent.py`

- [ ] **Step 1: Write the failing unit test** (pure — mock find + get_answer)

```python
def test_handle_cv_qa_single_candidate_returns_marker(monkeypatch):
    # A single match returns a delegation marker; the orchestrator runs the targeted RAG (no get_answer here).
    monkeypatch.setattr(cv_agent, "find_candidate_by_name", lambda db, cid, fids, name: [{"document_id": 11, "full_name": "Jean Dupont"}])
    ctx = cv_agent._CvContext("résume Jean", 1, None, 2, None, "gpt-4o-mini", 5, [7])
    out = cv_agent._handle_cv_qa({"candidate_name": "Jean Dupont", "question": "résume son parcours"}, ctx)
    assert out == {"stream_doc_id": 11, "question": "résume son parcours"}


def test_answer_cv_qa_runs_targeted_rag(monkeypatch):
    # End-to-end: router picks cv_qa, single match -> answer_cv runs get_answer scoped to that doc.
    monkeypatch.setattr(cv_agent, "route_cv_intent", lambda q, h, m: ("cv_qa", {"candidate_name": "Jean Dupont", "question": "résume"}))
    monkeypatch.setattr(cv_agent, "find_candidate_by_name", lambda db, cid, fids, name: [{"document_id": 11, "full_name": "Jean Dupont"}])
    captured = {}

    import rag_engine

    def fake_get_answer(question, user_id, db, selected_doc_ids=None, **k):
        captured["docs"] = selected_doc_ids
        return {"answer": "Jean is a senior engineer.", "sources": [{"document_id": 11}]}

    monkeypatch.setattr(rag_engine, "get_answer", fake_get_answer)
    out = cv_agent.answer_cv("résume Jean", 1, None, agent_id=2, history=None, model_id=None, company_id=5, folder_ids=[7])
    assert captured["docs"] == [11] and "senior engineer" in out["answer"]


def test_handle_cv_qa_no_candidate(monkeypatch):
    monkeypatch.setattr(cv_agent, "find_candidate_by_name", lambda db, cid, fids, name: [])
    ctx = cv_agent._CvContext("résume X", 1, None, 2, None, None, 5, [7])
    out = cv_agent._handle_cv_qa({"candidate_name": "Ghost", "question": "?"}, ctx)
    assert "Ghost" in out["answer"] and out["sources"] == []


def test_handle_cv_qa_ambiguous(monkeypatch):
    monkeypatch.setattr(cv_agent, "find_candidate_by_name", lambda db, cid, fids, name: [{"document_id": 1, "full_name": "Jean Dupont"}, {"document_id": 2, "full_name": "Jean Durand"}])
    ctx = cv_agent._CvContext("résume Jean", 1, None, 2, None, None, 5, [7])
    out = cv_agent._handle_cv_qa({"candidate_name": "Jean", "question": "?"}, ctx)
    assert "Jean Dupont" in out["answer"] and "Jean Durand" in out["answer"]  # asks to disambiguate


def test_cv_qa_registered():
    assert "cv_qa" in cv_agent._HANDLERS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -k cv_qa -v`
Expected: FAIL — `AttributeError: ... '_handle_cv_qa'`.

- [ ] **Step 3: Write minimal implementation** (append to `backend/cv_agent.py`)

```python
def _handle_cv_qa(args, ctx):
    """Q&A about one named candidate: resolve the name, then return a targeted-RAG marker.

    0 match / ambiguous -> a plain answer dict. Exactly 1 match -> a {"stream_doc_id","question"}
    marker; the orchestrator (answer_cv / answer_cv_stream) runs the single-CV RAG so get_answer
    is invoked exactly once, in the right (stream or non-stream) form.
    """
    name = (args.get("candidate_name") or "").strip()
    sub_question = (args.get("question") or ctx.question or "").strip()
    hits = find_candidate_by_name(ctx.db, ctx.company_id, ctx.folder_ids, name)
    if not hits:
        return {"answer": f"Je n'ai trouvé aucun candidat nommé « {name} » dans cette base.", "sources": []}
    if len(hits) > 1:
        names = ", ".join(h["full_name"] for h in hits[:8])
        return {"answer": f"Plusieurs candidats correspondent à « {name} » : {names}. Peux-tu préciser lequel ?", "sources": []}
    return {"stream_doc_id": hits[0]["document_id"], "question": sub_question}


_HANDLERS["cv_qa"] = _handle_cv_qa
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -k cv_qa -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Format + commit**

```bash
cd backend && python -m ruff format cv_agent.py tests/test_cv_agent.py && python -m ruff check cv_agent.py tests/test_cv_agent.py
git add backend/cv_agent.py backend/tests/test_cv_agent.py
git commit -m "feat(cv-agent): cv_qa handler (Phase 4 candidate Q&A)"
```

---

## Task 7: `search_candidates` + rank (Phase 2 data access)

**Files:** Modify `backend/cv_agent.py`; Test: `backend/tests/test_cv_agent.py` (pure rank test + DB test)

- [ ] **Step 1: Write the failing tests**

```python
def test_rank_candidates_orders_by_criteria_then_vector():
    rows = [
        {"document_id": 1, "matched_skills": ["python"], "similarity": 0.9},
        {"document_id": 2, "matched_skills": ["python", "react"], "similarity": 0.1},
        {"document_id": 3, "matched_skills": [], "similarity": 0.5},
    ]
    ranked = cv_agent._rank_candidates(rows)
    assert [r["document_id"] for r in ranked] == [2, 1, 3]  # more matched skills first, then similarity


def test_search_candidates_filters_and_groups(db_session, test_company):
    folder = CompanyFolder(company_id=test_company.id, name="CVs", is_cv_base=True)
    db_session.add(folder)
    db_session.flush()

    def mk(name, skills, seniority, years):
        doc = Document(filename=f"{name}.pdf", content="x", user_id=1, company_id=test_company.id,
                       is_company_rag=True, folder_id=folder.id)
        db_session.add(doc)
        db_session.flush()
        db_session.add(CandidateProfile(document_id=doc.id, company_id=test_company.id, folder_id=folder.id,
                                        full_name=name, skills=skills, seniority=seniority, years_experience=years,
                                        extraction_status="done"))
        db_session.flush()

    mk("A Py", ["python", "sql"], "senior", 8)
    mk("B React", ["react"], "junior", 1)
    mk("C PyReact", ["python", "react"], "lead", 12)

    res = cv_agent.search_candidates(db_session, test_company.id, [folder.id], skills=["python"], limit=10)
    names = {r["full_name"] for r in res}
    assert names == {"A Py", "C PyReact"}  # both have python; B filtered out
    res2 = cv_agent.search_candidates(db_session, test_company.id, [folder.id], skills=["python"], min_years=10)
    assert {r["full_name"] for r in res2} == {"C PyReact"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -k "rank_candidates or search_candidates" -v`
Expected: FAIL — `AttributeError: ... '_rank_candidates'`.

- [ ] **Step 3: Write minimal implementation** (append to `backend/cv_agent.py`)

Add import near the top:

```python
from cv_extraction import normalize_skills
```

Append:

```python
def _rank_candidates(rows):
    """Sort by number of matched skills (desc) then vector similarity (desc)."""
    return sorted(rows, key=lambda r: (len(r.get("matched_skills") or []), r.get("similarity") or 0.0), reverse=True)


def search_candidates(db, company_id, folder_ids, *, skills=None, seniority=None, location=None, min_years=None, query_embedding=None, agent_id=None, limit=10):
    """Return ranked distinct candidates matching the SQL filters (+ optional vector signal).

    Each result: {document_id, full_name, current_title, seniority, years_experience,
    matched_skills, similarity}.
    """
    from database import CandidateProfile

    if not company_id:
        return []
    wanted = normalize_skills(skills) if skills else []
    q = db.query(
        CandidateProfile.document_id,
        CandidateProfile.full_name,
        CandidateProfile.current_title,
        CandidateProfile.seniority,
        CandidateProfile.years_experience,
        CandidateProfile.skills,
    ).filter(
        CandidateProfile.company_id == company_id,
        CandidateProfile.extraction_status == "done",
    )
    if folder_ids:
        q = q.filter(CandidateProfile.folder_id.in_(folder_ids))
    if wanted:
        q = q.filter(CandidateProfile.skills.contains(wanted))  # skills @> [...]  (has ALL)
    if seniority:
        q = q.filter(CandidateProfile.seniority == seniority)
    if location:
        q = q.filter(CandidateProfile.location.ilike(f"%{location}%"))
    if min_years is not None:
        q = q.filter(CandidateProfile.years_experience >= min_years)

    rows = q.limit(200).all()

    # Optional vector signal: best chunk similarity per candidate document.
    sims = {}
    if query_embedding is not None and rows:
        import rag_engine

        doc_ids = [r[0] for r in rows]
        # Pass agent_id + company-RAG scope so the retrieval hits the company CV docs (the
        # user-level branch would filter on Document.user_id and match nothing here).
        hits = rag_engine.search_similar_texts_for_user(
            query_embedding, user_id=None, db=db, top_k=200, selected_doc_ids=doc_ids,
            agent_id=agent_id, company_id=company_id, include_company_rag=True,
            company_rag_folder_ids=folder_ids,
        )
        for h in hits:
            d = h.get("document_id")
            s = h.get("similarity") or 0.0
            if d not in sims or s > sims[d]:
                sims[d] = s

    out = []
    for r in rows:
        cand_skills = r[5] or []
        matched = [s for s in wanted if s in cand_skills]
        out.append({
            "document_id": r[0],
            "full_name": r[1],
            "current_title": r[2],
            "seniority": r[3],
            "years_experience": r[4],
            "matched_skills": matched,
            "similarity": sims.get(r[0], 0.0),
        })
    return _rank_candidates(out)[:limit]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -k "rank_candidates or search_candidates" -v`
Expected: `_rank_candidates` test PASSES; the DB test SKIPS locally (PASSES in CI).

- [ ] **Step 5: Format + commit**

```bash
cd backend && python -m ruff format cv_agent.py tests/test_cv_agent.py && python -m ruff check cv_agent.py tests/test_cv_agent.py
git add backend/cv_agent.py backend/tests/test_cv_agent.py
git commit -m "feat(cv-agent): search_candidates + ranking (Phase 2 data access)"
```

---

## Task 8: `cv_sourcing` handler + register (Phase 2 complete)

**Files:** Modify `backend/cv_agent.py`; Test: `backend/tests/test_cv_agent.py`

- [ ] **Step 1: Write the failing unit test** (pure — mock search + phrasing)

```python
def test_handle_cv_sourcing(monkeypatch):
    monkeypatch.setattr(cv_agent, "search_candidates", lambda db, cid, fids, **kw: [
        {"document_id": 3, "full_name": "C PyReact", "current_title": "Lead", "seniority": "lead", "years_experience": 12, "matched_skills": ["python", "react"], "similarity": 0.4},
    ])
    monkeypatch.setattr(cv_agent, "get_embedding_fast", lambda t: [0.0] * 1024)
    monkeypatch.setattr(cv_agent, "get_chat_response", lambda messages, model_id=None: "Voici 1 candidat : C PyReact (Lead).")

    ctx = cv_agent._CvContext("trouve des devs python react", 1, None, 2, None, "gpt-4o-mini", 5, [7])
    out = cv_agent._handle_cv_sourcing({"skills": ["python", "react"], "free_text": "dev python react"}, ctx)
    assert "C PyReact" in out["answer"]
    assert out["sources"] and out["sources"][0]["document_id"] == 3


def test_handle_cv_sourcing_no_match(monkeypatch):
    monkeypatch.setattr(cv_agent, "search_candidates", lambda db, cid, fids, **kw: [])
    monkeypatch.setattr(cv_agent, "get_embedding_fast", lambda t: [0.0] * 1024)
    ctx = cv_agent._CvContext("trouve des devs cobol", 1, None, 2, None, None, 5, [7])
    out = cv_agent._handle_cv_sourcing({"skills": ["cobol"]}, ctx)
    assert "aucun" in out["answer"].lower()


def test_cv_sourcing_registered():
    assert "cv_sourcing" in cv_agent._HANDLERS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -k "handle_cv_sourcing or cv_sourcing_registered" -v`
Expected: FAIL — `AttributeError: ... '_handle_cv_sourcing'`.

- [ ] **Step 3: Write minimal implementation** (append to `backend/cv_agent.py`)

Add import near the top:

```python
from mistral_embeddings import get_embedding_fast
```

Append:

```python
def _handle_cv_sourcing(args, ctx):
    """Rank candidates matching the recruiter's criteria and phrase the shortlist."""
    free_text = (args.get("free_text") or ctx.question or "").strip()
    query_embedding = None
    if free_text:
        try:
            query_embedding = get_embedding_fast(free_text)
        except Exception:
            query_embedding = None
    candidates = search_candidates(
        ctx.db, ctx.company_id, ctx.folder_ids,
        skills=args.get("skills"), seniority=args.get("seniority"),
        location=args.get("location"), min_years=args.get("min_years"),
        query_embedding=query_embedding, agent_id=ctx.agent_id, limit=10,
    )
    if not candidates:
        return {"answer": "Aucun candidat ne correspond à ces critères dans la base.", "sources": []}

    lines = [
        f"- {c['full_name']} — {c.get('current_title') or '?'} ({c.get('seniority') or '?'}, "
        f"{c.get('years_experience') if c.get('years_experience') is not None else '?'} ans) — "
        f"compétences: {', '.join(c.get('matched_skills') or []) or '—'}"
        for c in candidates
    ]
    prompt = (
        "Tu es un assistant de sourcing RH. Présente cette liste classée de candidats de façon "
        "concise et professionnelle, en français, sans inventer d'information.\n\n"
        "Demande initiale : " + ctx.question + "\n\nCandidats (déjà classés) :\n" + "\n".join(lines)
    )
    answer = get_chat_response([{"role": "user", "content": prompt}], model_id=ctx.model_id)
    sources = [
        {"text": c["full_name"], "document_name": c["full_name"], "score": c.get("similarity") or 0.0, "document_id": c["document_id"]}
        for c in candidates
    ]
    return {"answer": answer, "sources": sources}


_HANDLERS["cv_sourcing"] = _handle_cv_sourcing
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -k "handle_cv_sourcing or cv_sourcing_registered" -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Format + commit**

```bash
cd backend && python -m ruff format cv_agent.py tests/test_cv_agent.py && python -m ruff check cv_agent.py tests/test_cv_agent.py
git add backend/cv_agent.py backend/tests/test_cv_agent.py
git commit -m "feat(cv-agent): cv_sourcing handler (Phase 2 sourcing)"
```

---

## Task 9: `aggregate_candidates` (Phase 3 data access, whitelisted SQL)

**Files:** Modify `backend/cv_agent.py`; Test: `backend/tests/test_cv_agent.py` (pure validation test + DB test)

- [ ] **Step 1: Write the failing tests**

```python
import pytest


def test_aggregate_rejects_unknown_metric_dimension():
    with pytest.raises(ValueError):
        cv_agent.aggregate_candidates(None, 1, [1], metric="drop_table", dimension="skill")
    with pytest.raises(ValueError):
        cv_agent.aggregate_candidates(None, 1, [1], metric="count", dimension="ssn")


def test_aggregate_candidates_db(db_session, test_company):
    folder = CompanyFolder(company_id=test_company.id, name="CVs", is_cv_base=True)
    db_session.add(folder)
    db_session.flush()

    def mk(name, skills, seniority, years):
        doc = Document(filename=f"{name}.pdf", content="x", user_id=1, company_id=test_company.id,
                       is_company_rag=True, folder_id=folder.id)
        db_session.add(doc)
        db_session.flush()
        db_session.add(CandidateProfile(document_id=doc.id, company_id=test_company.id, folder_id=folder.id,
                                        full_name=name, skills=skills, seniority=seniority, years_experience=years,
                                        extraction_status="done"))
        db_session.flush()

    mk("A", ["python", "sql"], "senior", 8)
    mk("B", ["python"], "junior", 2)
    mk("C", ["react"], "senior", 6)

    by_skill = cv_agent.aggregate_candidates(db_session, test_company.id, [folder.id], metric="count", dimension="skill")
    counts = {r["key"]: r["value"] for r in by_skill["rows"]}
    assert counts["python"] == 2 and counts["sql"] == 1 and counts["react"] == 1

    avg = cv_agent.aggregate_candidates(db_session, test_company.id, [folder.id], metric="avg_experience", dimension="seniority")
    assert round(avg["rows"][0]["value"]) == round((8 + 2 + 6) / 3)

    dist = cv_agent.aggregate_candidates(db_session, test_company.id, [folder.id], metric="distribution", dimension="seniority")
    dcounts = {r["key"]: r["value"] for r in dist["rows"]}
    assert dcounts["senior"] == 2 and dcounts["junior"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -k aggregate -v`
Expected: FAIL — `AttributeError: ... 'aggregate_candidates'`.

- [ ] **Step 3: Write minimal implementation** (append to `backend/cv_agent.py`)

Add import near the top:

```python
from sqlalchemy import text, bindparam
```

Append:

```python
_ALLOWED_METRICS = {"count", "avg_experience", "distribution"}
_ALLOWED_DIMENSIONS = {"skill", "seniority", "location", "language"}
# Whitelisted column/expression per dimension — NEVER interpolate user input as SQL identifiers.
_DIM_COLUMN = {"seniority": "seniority", "location": "location"}
_DIM_JSONB = {"skill": "skills", "language": "languages"}


def _aggregate_filters(filter_dict):
    """Return (sql_fragment, params) for the optional filter, using bound params only."""
    frags, params = [], {}
    f = filter_dict or {}
    if f.get("skill"):
        frags.append("skills @> :f_skill")
        params["f_skill"] = json.dumps([normalize_skills([f["skill"]])[0]]) if normalize_skills([f["skill"]]) else "[]"
    if f.get("seniority"):
        frags.append("seniority = :f_seniority")
        params["f_seniority"] = f["seniority"]
    if f.get("location"):
        frags.append("location ILIKE :f_location")
        params["f_location"] = f"%{f['location']}%"
    if f.get("min_years") is not None:
        frags.append("years_experience >= :f_min_years")
        params["f_min_years"] = int(f["min_years"])
    return ("".join(" AND " + fr for fr in frags), params)


def aggregate_candidates(db, company_id, folder_ids, *, metric, dimension, filter=None):
    """Whitelisted aggregation over candidate_profiles. Returns {metric, dimension, rows, total}."""
    if metric not in _ALLOWED_METRICS:
        raise ValueError(f"unknown metric: {metric}")
    if dimension not in _ALLOWED_DIMENSIONS:
        raise ValueError(f"unknown dimension: {dimension}")
    if not company_id:
        return {"metric": metric, "dimension": dimension, "rows": [], "total": 0}

    filt_sql, params = _aggregate_filters(filter)
    params["cid"] = company_id
    where = "cp.company_id = :cid AND cp.extraction_status = 'done'" + filt_sql
    folder_join = ""
    if folder_ids:
        where += " AND cp.folder_id IN :fids"
        params["fids"] = tuple(folder_ids)

    if metric == "avg_experience":
        sql = f"SELECT AVG(cp.years_experience)::float AS v, COUNT(*) AS n FROM candidate_profiles cp WHERE {where}"
        stmt = text(sql)
        if folder_ids:
            stmt = stmt.bindparams(bindparam("fids", expanding=True))
        row = db.execute(stmt, params).first()
        avg = row[0] if row and row[0] is not None else 0.0
        return {"metric": metric, "dimension": dimension, "rows": [{"key": "avg_experience", "value": avg}], "total": int(row[1]) if row else 0}

    # count / distribution -> GROUP BY dimension
    if dimension in _DIM_JSONB:
        col = _DIM_JSONB[dimension]
        sql = (
            f"SELECT elem AS k, COUNT(*) AS v FROM candidate_profiles cp, "
            f"jsonb_array_elements_text(cp.{col}) AS elem WHERE {where} "
            f"GROUP BY elem ORDER BY v DESC LIMIT 50"
        )
    else:
        col = _DIM_COLUMN[dimension]
        sql = (
            f"SELECT COALESCE(cp.{col}, 'inconnu') AS k, COUNT(*) AS v FROM candidate_profiles cp "
            f"WHERE {where} GROUP BY cp.{col} ORDER BY v DESC LIMIT 50"
        )
    stmt = text(sql)
    if folder_ids:
        stmt = stmt.bindparams(bindparam("fids", expanding=True))
    rows = [{"key": r[0], "value": int(r[1])} for r in db.execute(stmt, params).all()]
    return {"metric": metric, "dimension": dimension, "rows": rows, "total": sum(r["value"] for r in rows)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -k aggregate -v`
Expected: the validation test PASSES; the DB test SKIPS locally (PASSES in CI).

- [ ] **Step 5: Format + commit**

```bash
cd backend && python -m ruff format cv_agent.py tests/test_cv_agent.py && python -m ruff check cv_agent.py tests/test_cv_agent.py
git add backend/cv_agent.py backend/tests/test_cv_agent.py
git commit -m "feat(cv-agent): aggregate_candidates whitelisted SQL (Phase 3 data access)"
```

---

## Task 10: `cv_analytics` handler + register (Phase 3 complete)

**Files:** Modify `backend/cv_agent.py`; Test: `backend/tests/test_cv_agent.py`

- [ ] **Step 1: Write the failing unit test** (pure — mock aggregate + phrasing)

```python
def test_handle_cv_analytics(monkeypatch):
    monkeypatch.setattr(cv_agent, "aggregate_candidates", lambda db, cid, fids, **kw: {
        "metric": "count", "dimension": "skill",
        "rows": [{"key": "python", "value": 2}, {"key": "react", "value": 1}], "total": 3,
    })
    monkeypatch.setattr(cv_agent, "get_chat_response", lambda messages, model_id=None: "Python: 2, React: 1.")
    ctx = cv_agent._CvContext("combien maîtrisent chaque techno", 1, None, 2, None, "gpt-4o-mini", 5, [7])
    out = cv_agent._handle_cv_analytics({"metric": "count", "dimension": "skill"}, ctx)
    assert "Python" in out["answer"]
    assert out["sources"] == []


def test_handle_cv_analytics_bad_args_returns_none(monkeypatch):
    # Invalid enum -> aggregate raises -> handler returns None (router falls back to RAG).
    ctx = cv_agent._CvContext("x", 1, None, 2, None, None, 5, [7])
    assert cv_agent._handle_cv_analytics({"metric": "nope", "dimension": "skill"}, ctx) is None


def test_cv_analytics_registered():
    assert "cv_analytics" in cv_agent._HANDLERS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -k "handle_cv_analytics or cv_analytics_registered" -v`
Expected: FAIL — `AttributeError: ... '_handle_cv_analytics'`.

- [ ] **Step 3: Write minimal implementation** (append to `backend/cv_agent.py`)

```python
def _handle_cv_analytics(args, ctx):
    """Run a whitelisted aggregation and phrase the numbers. Returns None on invalid args (-> RAG fallback)."""
    try:
        result = aggregate_candidates(
            ctx.db, ctx.company_id, ctx.folder_ids,
            metric=args.get("metric"), dimension=args.get("dimension"), filter=args.get("filter"),
        )
    except ValueError:
        return None

    if not result["rows"]:
        return {"answer": "Je n'ai pas de données correspondant à cette demande dans la base.", "sources": []}

    table = "\n".join(f"{r['key']}: {r['value']}" for r in result["rows"][:30])
    prompt = (
        "Tu es un assistant analytics RH. Réponds en français, de façon concise, en t'appuyant "
        "STRICTEMENT sur ces chiffres agrégés (n'invente rien).\n\n"
        f"Question : {ctx.question}\n"
        f"Résultat ({result['metric']} par {result['dimension']}, total={result['total']}) :\n{table}"
    )
    answer = get_chat_response([{"role": "user", "content": prompt}], model_id=ctx.model_id)
    return {"answer": answer, "sources": []}


_HANDLERS["cv_analytics"] = _handle_cv_analytics
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cv_agent.py -k "handle_cv_analytics or cv_analytics_registered" -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Format + commit**

```bash
cd backend && python -m ruff format cv_agent.py tests/test_cv_agent.py && python -m ruff check cv_agent.py tests/test_cv_agent.py
git add backend/cv_agent.py backend/tests/test_cv_agent.py
git commit -m "feat(cv-agent): cv_analytics handler (Phase 3 analytics)"
```

---

## Final verification

- [ ] **Full suite + format + lint**

Run:
```bash
cd backend && python -m ruff format --check . && python -m ruff check . && python -m pytest -q
```
Expected: format clean, lint clean, all green (CV DB tests run only in CI with a real Postgres).

- [ ] **Manual smoke (after deploy, on a CV-base companion)**
  - Q&A: "Résume le parcours de {nom présent dans la base}" → grounded answer.
  - Sourcing: "Trouve des développeurs Python seniors" → ranked shortlist with CV links.
  - Analytics: "Combien de candidats maîtrisent SQL ?", "Séniorité moyenne ?", "Répartition par ville ?" → real numbers.
  - Non-CV small talk on the same companion → normal RAG answer (fallback intact).
