# Companion CV — Phase 1 (Fondation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundation that lets a flagged "CV base" folder extract structured candidate metadata at ingestion time, so later phases (sourcing, analytics, Q&A) can query it — reusing the existing folder-import + RAG ingestion machinery.

**Architecture:** A new `CandidateProfile` table (1:1 with `Document`) stores structured fields extracted by one JSON-mode LLM call per CV. A `is_cv_base` flag on `CompanyFolder` turns the extraction step on inside the *existing* `ingest_file` callback of `run_folder_import`. Idempotency is free: a CV is skipped if its `CandidateProfile` already exists. Embeddings are batched for throughput. No new infrastructure, no Cloud Run Job, no bespoke pipeline.

**Tech Stack:** FastAPI / SQLAlchemy / PostgreSQL + pgvector, Mistral embeddings, OpenAI/Mistral/Gemini chat clients (`get_chat_response_json`), pytest (+ real-PG DB tests gated by `DATABASE_URL`).

---

## Scope & boundaries

**In scope (Phase 1):** data model, the `is_cv_base` flag, the pure extraction logic, the LLM extraction wrapper, batch embeddings, wiring extraction into the existing company-RAG import callback, idempotency, and raising the file cap for CV-base imports.

**Out of scope (later phases / pending §8 of the spec):**
- The bulk **source** of the 80k files (GCS prefix vs Drive) — the file format is unconfirmed with the client. Phase 1 plugs into the *existing* import entry point (`POST /api/company-rag/folders/import`); a dedicated bulk source is a follow-on once the format is confirmed.
- Sourcing / analytics / Q&A query tools (Phases 2–4).

**Spec reference:** `docs/superpowers/specs/2026-06-30-companion-80k-cv-simplified-design.md`.

## File structure

| File | Responsibility | Create/Modify |
|---|---|---|
| `backend/cv_extraction.py` | Pure CV logic: skill normalization, extraction schema, coercion, the LLM extraction wrapper, the `CandidateProfile` upsert helper | **Create** |
| `backend/database.py` | `CandidateProfile` model; `is_cv_base` column on `CompanyFolder`; migration entries; `ensure_candidate_profile_indexes()` | Modify |
| `backend/mistral_embeddings.py` | `get_embeddings_batch(texts)` | Modify |
| `backend/rag_engine.py` | `ingest_text_content` embedding loop → batched | Modify |
| `backend/routers/company_rag.py` | `ingest_file` runs extraction when the target folder `is_cv_base`; raise the file cap for CV-base imports | Modify |
| `backend/tests/test_cv_extraction.py` | Pure unit tests (no DB) | **Create** |
| `backend/tests/test_cv_ingestion.py` | DB + integration tests (mocked LLM/embeddings) | **Create** |

**Conventions to follow** (verified in the codebase):
- Pure logic lives in importable modules and is unit-tested without a DB (see `tests/test_folder_import.py`).
- DB tests use the `db_session` fixture (`tests/conftest.py`), which is auto-skipped when `DATABASE_URL` is not a real Postgres.
- New tables are created by `Base.metadata.create_all` inside `init_db()` (`database.py:1023`). Single-column indexes via `index=True`. Special indexes (GIN) via an `ensure_*` startup function (pattern: `ensure_pgvector` at `database.py:1034`, `ensure_llm_usage_table` at `1449`).
- New columns on existing tables: append a `(table, column, col_def)` tuple to the `migrations` list (`database.py` ~line 1180) — it runs `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.

---

## Task 1: Skill normalization (pure)

**Files:**
- Create: `backend/cv_extraction.py`
- Test: `backend/tests/test_cv_extraction.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_cv_extraction.py
from cv_extraction import normalize_skill, normalize_skills


def test_normalize_skill_lowercases_and_trims():
    assert normalize_skill("  ReactJS ") == "react"
    assert normalize_skill("React.js") == "react"
    assert normalize_skill("Node.JS") == "node"
    assert normalize_skill("C++") == "c++"


def test_normalize_skills_dedupes_and_drops_empty():
    assert normalize_skills(["React", "react.js", "", None, "Python"]) == ["react", "python"]
    assert normalize_skills(None) == []
    assert normalize_skills("not a list") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cv_extraction.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cv_extraction'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/cv_extraction.py
"""CV metadata extraction: pure normalization/coercion + the LLM extraction wrapper
and the CandidateProfile upsert helper. Kept DB-agnostic where possible so the bulk of
the logic is unit-testable without a database or an LLM."""

import logging

logger = logging.getLogger(__name__)

# Canonical aliases applied AFTER lowercasing + stripping common suffixes.
_SKILL_ALIASES = {
    "reactjs": "react",
    "nodejs": "node",
}
# Suffixes stripped before alias lookup ("react.js" -> "react").
_SKILL_SUFFIXES = (".js", ".net")


def normalize_skill(raw):
    """Lowercase, trim, strip common suffixes, and map known aliases. Returns '' if empty."""
    if not raw or not isinstance(raw, str):
        return ""
    s = raw.strip().lower()
    for suf in _SKILL_SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)]
    s = _SKILL_ALIASES.get(s, s)
    return s.strip()


def normalize_skills(raw):
    """Normalize a list of skills, dropping empties and de-duplicating (order-preserving)."""
    if not isinstance(raw, list):
        return []
    seen = []
    for item in raw:
        norm = normalize_skill(item)
        if norm and norm not in seen:
            seen.append(norm)
    return seen
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cv_extraction.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/cv_extraction.py backend/tests/test_cv_extraction.py
git commit -m "feat(cv): skill normalization helpers"
```

---

## Task 2: Extraction schema + profile coercion (pure)

**Files:**
- Modify: `backend/cv_extraction.py`
- Test: `backend/tests/test_cv_extraction.py`

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_cv_extraction.py
from cv_extraction import CV_EXTRACTION_SCHEMA, coerce_cv_profile


def test_coerce_cv_profile_happy_path():
    raw = {
        "full_name": "Jean Dupont",
        "current_title": "Senior Backend Engineer",
        "seniority": "senior",
        "years_experience": "8",          # string -> int
        "skills": ["Python", "react.js"], # normalized
        "languages": ["French", "English"],
        "education_level": "Master",
        "location": "Paris",
        "last_company": "ACME",
        "summary": "Experienced engineer.",
    }
    p = coerce_cv_profile(raw)
    assert p["full_name"] == "Jean Dupont"
    assert p["years_experience"] == 8
    assert p["skills"] == ["python", "react"]
    assert p["languages"] == ["french", "english"]


def test_coerce_cv_profile_handles_missing_and_garbage():
    p = coerce_cv_profile({"years_experience": "n/a", "skills": "Python"})
    assert p["full_name"] is None
    assert p["years_experience"] is None      # unparseable -> None
    assert p["skills"] == []                   # non-list -> []
    assert p["raw_extraction"] == {"years_experience": "n/a", "skills": "Python"}


def test_schema_lists_expected_fields():
    props = CV_EXTRACTION_SCHEMA["properties"]
    for field in ("full_name", "skills", "years_experience", "seniority", "location"):
        assert field in props
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cv_extraction.py -v`
Expected: FAIL — `ImportError: cannot import name 'CV_EXTRACTION_SCHEMA'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/cv_extraction.py

CV_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "full_name": {"type": "string"},
        "current_title": {"type": "string"},
        "seniority": {"type": "string", "description": "junior / confirmé / senior / lead"},
        "years_experience": {"type": "integer"},
        "skills": {"type": "array", "items": {"type": "string"}},
        "languages": {"type": "array", "items": {"type": "string"}},
        "education_level": {"type": "string"},
        "location": {"type": "string"},
        "last_company": {"type": "string"},
        "summary": {"type": "string"},
    },
}

# Scalar string fields copied through verbatim (trimmed).
_STR_FIELDS = ("full_name", "current_title", "seniority", "education_level", "location", "last_company", "summary")


def _coerce_int(value):
    """Best-effort int coercion. Returns None when not parseable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _coerce_str(value):
    if not value or not isinstance(value, str):
        return None
    return value.strip() or None


def coerce_cv_profile(raw):
    """Coerce a raw LLM extraction dict into a clean profile dict with stable types.

    Always preserves the untouched LLM output under ``raw_extraction`` so we can
    re-derive fields later without re-calling the model. Never raises on bad input.
    """
    raw = raw if isinstance(raw, dict) else {}
    profile = {field: _coerce_str(raw.get(field)) for field in _STR_FIELDS}
    profile["years_experience"] = _coerce_int(raw.get("years_experience"))
    profile["skills"] = normalize_skills(raw.get("skills"))
    profile["languages"] = normalize_skills(raw.get("languages"))
    profile["raw_extraction"] = raw
    return profile
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cv_extraction.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/cv_extraction.py backend/tests/test_cv_extraction.py
git commit -m "feat(cv): extraction schema + profile coercion"
```

---

## Task 3: LLM extraction wrapper

**Files:**
- Modify: `backend/cv_extraction.py`
- Test: `backend/tests/test_cv_extraction.py`

Reuses `openai_client.get_chat_response_json(messages, schema, model_id, retries)` (verified at `openai_client.py:610`), which returns a parsed dict and retries on bad JSON.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_cv_extraction.py
import cv_extraction


def test_extract_cv_metadata_calls_llm_and_coerces(monkeypatch):
    captured = {}

    def fake_json(messages, schema=None, model_id=None, retries=2):
        captured["schema"] = schema
        captured["model_id"] = model_id
        captured["text"] = messages[-1]["content"]
        return {"full_name": "Jane Doe", "years_experience": "5", "skills": ["React"]}

    monkeypatch.setattr(cv_extraction, "get_chat_response_json", fake_json)

    profile = cv_extraction.extract_cv_metadata("CV TEXT HERE", model_id="gpt-4o-mini")

    assert profile["full_name"] == "Jane Doe"
    assert profile["years_experience"] == 5
    assert profile["skills"] == ["react"]
    assert captured["schema"] is cv_extraction.CV_EXTRACTION_SCHEMA
    assert captured["model_id"] == "gpt-4o-mini"
    assert "CV TEXT HERE" in captured["text"]


def test_extract_cv_metadata_truncates_long_text(monkeypatch):
    monkeypatch.setattr(cv_extraction, "get_chat_response_json", lambda *a, **k: {})
    # Should not raise on very long input.
    cv_extraction.extract_cv_metadata("x" * 100_000)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cv_extraction.py -v`
Expected: FAIL — `AttributeError: module 'cv_extraction' has no attribute 'extract_cv_metadata'`

- [ ] **Step 3: Write minimal implementation**

```python
# add near the top of backend/cv_extraction.py (with the other imports)
from openai_client import get_chat_response_json

# Cap the text we send to the extractor; CVs are short and this bounds cost/latency.
_MAX_EXTRACT_CHARS = 24000

_EXTRACTION_SYSTEM_PROMPT = (
    "You extract structured data from a single candidate CV. "
    "Return ONLY a JSON object matching the schema. Use null for unknown fields. "
    "skills and languages must be arrays of short lowercase tokens."
)


# append to backend/cv_extraction.py
def extract_cv_metadata(text, model_id=None):
    """Run one JSON-mode LLM call to extract candidate metadata from CV text.

    Returns a coerced profile dict (see ``coerce_cv_profile``). Raises if the LLM
    call itself fails after its internal retries.
    """
    snippet = (text or "")[:_MAX_EXTRACT_CHARS]
    messages = [
        {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": "CV:\n" + snippet},
    ]
    raw = get_chat_response_json(messages, schema=CV_EXTRACTION_SCHEMA, model_id=model_id, retries=2)
    return coerce_cv_profile(raw)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cv_extraction.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/cv_extraction.py backend/tests/test_cv_extraction.py
git commit -m "feat(cv): LLM extraction wrapper (JSON mode)"
```

---

## Task 4: Batch embeddings

**Files:**
- Modify: `backend/mistral_embeddings.py`
- Test: `backend/tests/test_cv_extraction.py` (add an embeddings section; no DB needed)

`get_embedding`/`get_embedding_fast` embed one text per call (`mistral_embeddings.py:53,81`). Add a batch function that (a) serves cache hits, (b) sends only cache misses to the API in groups, and (c) returns embeddings in the SAME order as the input.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_cv_extraction.py
import mistral_embeddings


def test_get_embeddings_batch_preserves_order_and_uses_cache(monkeypatch):
    # No Redis cache in the test: force misses.
    monkeypatch.setattr(mistral_embeddings, "_get_cached_embedding", lambda t: None)
    monkeypatch.setattr(mistral_embeddings, "_set_cached_embedding", lambda t, e: None)

    calls = {"n": 0}

    class _Resp:
        def __init__(self, inputs):
            # One data item per input, embedding encodes the input length for assertion.
            self.data = [type("D", (), {"embedding": [float(len(s))]})() for s in inputs]

    class _Client:
        class embeddings:
            @staticmethod
            def create(model, inputs):
                calls["n"] += 1
                return _Resp(inputs)

    monkeypatch.setattr(mistral_embeddings, "_get_client", lambda: _Client())

    out = mistral_embeddings.get_embeddings_batch(["a", "bbb", "cc"], batch_size=2)
    assert out == [[1.0], [3.0], [2.0]]   # order preserved
    assert calls["n"] == 2                 # 3 items, batch_size 2 -> 2 API calls


def test_get_embeddings_batch_empty():
    assert mistral_embeddings.get_embeddings_batch([]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cv_extraction.py -k embeddings_batch -v`
Expected: FAIL — `AttributeError: module 'mistral_embeddings' has no attribute 'get_embeddings_batch'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/mistral_embeddings.py
def get_embeddings_batch(texts: List[str], batch_size: int = 64) -> List[List[float]]:
    """Embed many texts, returning embeddings in the same order as ``texts``.

    Serves cache hits individually; sends only cache misses to the API in groups of
    ``batch_size`` (the Mistral embeddings endpoint accepts a list of inputs per call).
    Raises on API failure (no zero-vector fallback), consistent with get_embedding.
    """
    if not texts:
        return []

    results: List[List[float]] = [None] * len(texts)
    miss_indices: List[int] = []
    for i, t in enumerate(texts):
        cached = _get_cached_embedding(t)
        if cached is not None:
            results[i] = cached
        else:
            miss_indices.append(i)

    for start in range(0, len(miss_indices), batch_size):
        group = miss_indices[start : start + batch_size]
        inputs = [texts[i] for i in group]
        client = _get_client()
        response = client.embeddings.create(model=EMBEDDING_MODEL, inputs=inputs)
        for idx, item in zip(group, response.data):
            emb = item.embedding
            results[idx] = emb
            _set_cached_embedding(texts[idx], emb)

    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cv_extraction.py -k embeddings_batch -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/mistral_embeddings.py backend/tests/test_cv_extraction.py
git commit -m "feat(embeddings): order-preserving batch embedding helper"
```

---

## Task 5: Batch the ingestion embedding loop

**Files:**
- Modify: `backend/rag_engine.py:1222-1249` (the per-chunk embedding loop inside `ingest_text_content`)
- Test: `backend/tests/test_cv_ingestion.py` (DB)

Replace the per-chunk, per-sub-chunk `get_embedding_fast` loop with a single `get_embeddings_batch` call over all sub-chunks, then average sub-chunk embeddings back per chunk (preserving current behavior for oversized chunks). This speeds up ALL ingestion and keeps one embedding path (DRY).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_cv_ingestion.py
import rag_engine
from database import Document, DocumentChunk


def test_ingest_text_content_batches_embeddings(db_session, test_user, test_agent, monkeypatch):
    batch_calls = {"n": 0}

    def fake_batch(texts, batch_size=64):
        batch_calls["n"] += 1
        return [[0.1] * 1024 for _ in texts]

    # ingest_text_content imports get_embeddings_batch from mistral_embeddings.
    monkeypatch.setattr(rag_engine, "get_embeddings_batch", fake_batch, raising=False)
    monkeypatch.setattr("mistral_embeddings.get_embeddings_batch", fake_batch, raising=False)

    text = "Paragraph one. " * 50
    doc_id = rag_engine.ingest_text_content(
        text_content=text, filename="cv.txt", user_id=test_user.id,
        agent_id=test_agent.id, db=db_session, company_id=test_user.company_id,
    )

    doc = db_session.query(Document).filter(Document.id == doc_id).first()
    assert doc is not None
    chunks = db_session.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).all()
    assert len(chunks) >= 1
    assert all(c.embedding_vec is not None for c in chunks)
    assert batch_calls["n"] >= 1            # used the batch path, not per-chunk
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cv_ingestion.py -k batches_embeddings -v`
Expected: FAIL — either an `AttributeError` (no `get_embeddings_batch` import in `rag_engine`) or `batch_calls["n"] == 0` because the old per-chunk path is still used. (If `DATABASE_URL` is unset the test is skipped — run against a real PG, see the conftest gate.)

- [ ] **Step 3: Write minimal implementation**

In `backend/rag_engine.py`, update the import at line 10:

```python
from mistral_embeddings import get_embedding, get_embedding_fast, get_embeddings_batch
```

Replace the embedding loop (currently `rag_engine.py:1222-1249`, the `for i, chunk in enumerate(chunks):` block that calls `get_embedding_fast` and creates `DocumentChunk`s) with:

```python
        # Flatten every chunk into its sub-chunks (oversized chunks split further),
        # batch-embed them all in one path, then average sub-chunk vectors per chunk.
        sub_texts = []
        sub_owner = []  # parallel to sub_texts: index of the owning chunk
        for i, chunk in enumerate(chunks):
            for sub in split_for_embedding(chunk, 8192):
                sub_texts.append(sub)
                sub_owner.append(i)

        if progress_callback:
            progress_callback("embedding", 50, len(chunks))

        sub_embeddings = get_embeddings_batch(sub_texts)

        by_chunk = {}
        for owner, emb in zip(sub_owner, sub_embeddings):
            by_chunk.setdefault(owner, []).append(emb)

        for i, chunk in enumerate(chunks):
            embs = by_chunk.get(i)
            if not embs:
                raise ValueError(f"No sub-chunks produced for chunk {i}")
            avg_embedding = list(np.mean(np.array(embs), axis=0))
            doc_chunk = DocumentChunk(
                document_id=document.id,
                company_id=company_id,
                chunk_text=chunk,
                embedding_vec=avg_embedding,
                chunk_index=i,
            )
            db.add(doc_chunk)
        db.commit()
```

Leave the `split_for_embedding` helper (defined just above at `rag_engine.py:1214`) and the surrounding try/except/rollback intact.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cv_ingestion.py -k batches_embeddings -v`
Expected: PASS. Then run the existing suite to check for regressions: `cd backend && python -m pytest -q`
Expected: no new failures.

- [ ] **Step 5: Commit**

```bash
git add backend/rag_engine.py backend/tests/test_cv_ingestion.py
git commit -m "perf(rag): batch chunk embeddings in ingest_text_content"
```

---

## Task 6: `CandidateProfile` model + indexes

**Files:**
- Modify: `backend/database.py` (add model near `DocumentChunk` ~line 665; add `ensure_candidate_profile_indexes()` near `ensure_llm_usage_table` ~line 1449; call it at startup)
- Test: `backend/tests/test_cv_ingestion.py` (DB)

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_cv_ingestion.py
from database import CandidateProfile


def test_candidate_profile_crud(db_session, test_user, test_agent):
    doc = Document(filename="cv.pdf", content="x", user_id=test_user.id,
                   agent_id=test_agent.id, company_id=test_user.company_id, is_company_rag=True)
    db_session.add(doc)
    db_session.flush()

    profile = CandidateProfile(
        document_id=doc.id, company_id=test_user.company_id,
        full_name="Jean Dupont", seniority="senior", years_experience=8,
        skills=["python", "react"], languages=["french"],
        raw_extraction={"summary": "x"}, extraction_status="done", extraction_model="gpt-4o-mini",
    )
    db_session.add(profile)
    db_session.flush()

    fetched = db_session.query(CandidateProfile).filter(CandidateProfile.document_id == doc.id).first()
    assert fetched.full_name == "Jean Dupont"
    assert fetched.skills == ["python", "react"]
    assert fetched.years_experience == 8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cv_ingestion.py -k candidate_profile_crud -v`
Expected: FAIL — `ImportError: cannot import name 'CandidateProfile'`

- [ ] **Step 3: Write minimal implementation**

Add the model after `DocumentChunk` (`database.py` ~line 665). Note `JSONB`/`Vector` import: `from sqlalchemy.dialects.postgresql import JSONB` (add to the postgresql imports near the top if not present).

```python
class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    folder_id = Column(Integer, ForeignKey("company_folders.id", ondelete="SET NULL"), nullable=True, index=True)

    full_name = Column(Text, nullable=True)
    current_title = Column(Text, nullable=True)
    location = Column(Text, nullable=True, index=True)
    seniority = Column(Text, nullable=True, index=True)
    years_experience = Column(Integer, nullable=True, index=True)

    skills = Column(JSONB, nullable=True)
    languages = Column(JSONB, nullable=True)
    education_level = Column(Text, nullable=True)
    last_company = Column(Text, nullable=True)

    raw_extraction = Column(JSONB, nullable=True)
    extraction_status = Column(String(20), nullable=False, default="done", server_default="done")
    extraction_model = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
```

Add the GIN index helper near `ensure_llm_usage_table` (`database.py:1449`):

```python
def ensure_candidate_profile_indexes():
    """GIN index on candidate_profiles.skills for skill filter + aggregation. Idempotent."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SET lock_timeout = '5s'"))
            conn.execute(text("SET statement_timeout = '30s'"))
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_candidate_profiles_skills_gin "
                    "ON candidate_profiles USING gin (skills)"
                )
            )
            conn.commit()
            logger.info("ensure_candidate_profile_indexes: OK")
    except Exception as e:
        logger.warning(f"ensure_candidate_profile_indexes skipped: {e}")
```

Wire it into startup: find where `ensure_pgvector()` / `ensure_columns()` are called at app startup (`grep -rn "ensure_pgvector()" backend`) and add `ensure_candidate_profile_indexes()` right after, so it runs after `create_all` has made the table.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cv_ingestion.py -k candidate_profile_crud -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/database.py backend/tests/test_cv_ingestion.py
git commit -m "feat(cv): CandidateProfile model + skills GIN index"
```

---

## Task 7: `is_cv_base` flag on `CompanyFolder`

**Files:**
- Modify: `backend/database.py` (`CompanyFolder` model ~line 585; `migrations` list ~line 1180)
- Test: `backend/tests/test_cv_ingestion.py` (DB)

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_cv_ingestion.py
from database import CompanyFolder


def test_company_folder_is_cv_base_defaults_false(db_session, test_user):
    folder = CompanyFolder(company_id=test_user.company_id, name="CVs")
    db_session.add(folder)
    db_session.flush()
    db_session.refresh(folder)
    assert folder.is_cv_base is False

    folder.is_cv_base = True
    db_session.flush()
    db_session.refresh(folder)
    assert folder.is_cv_base is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cv_ingestion.py -k is_cv_base -v`
Expected: FAIL — `AttributeError: 'CompanyFolder' object has no attribute 'is_cv_base'`

- [ ] **Step 3: Write minimal implementation**

Add to the `CompanyFolder` model (`database.py` ~line 585, after `name`):

```python
    is_cv_base = Column(Boolean, default=False, nullable=False, server_default="false")
```

Add to the `migrations` list (`database.py` ~line 1182, end of the list) so existing DBs get the column:

```python
        # Companion CV base
        ("company_folders", "is_cv_base", "BOOLEAN NOT NULL DEFAULT FALSE"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cv_ingestion.py -k is_cv_base -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/database.py backend/tests/test_cv_ingestion.py
git commit -m "feat(cv): is_cv_base flag on company folders"
```

---

## Task 8: `upsert_candidate_profile` helper (idempotency)

**Files:**
- Modify: `backend/cv_extraction.py`
- Test: `backend/tests/test_cv_ingestion.py` (DB)

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_cv_ingestion.py
from cv_extraction import upsert_candidate_profile


def _make_cv_doc(db_session, test_user, test_agent):
    doc = Document(filename="cv.pdf", content="x", user_id=test_user.id,
                   agent_id=test_agent.id, company_id=test_user.company_id, is_company_rag=True)
    db_session.add(doc)
    db_session.flush()
    return doc


def test_upsert_candidate_profile_creates_then_skips(db_session, test_user, test_agent):
    doc = _make_cv_doc(db_session, test_user, test_agent)
    profile = {"full_name": "Jane", "years_experience": 5, "skills": ["python"],
               "languages": [], "raw_extraction": {"summary": "x"}}

    created = upsert_candidate_profile(
        db_session, document_id=doc.id, company_id=test_user.company_id,
        folder_id=None, profile=profile, model_id="gpt-4o-mini",
    )
    assert created is True
    assert db_session.query(CandidateProfile).filter(CandidateProfile.document_id == doc.id).count() == 1

    # Second call is idempotent: skipped, no duplicate.
    again = upsert_candidate_profile(
        db_session, document_id=doc.id, company_id=test_user.company_id,
        folder_id=None, profile=profile, model_id="gpt-4o-mini",
    )
    assert again is False
    assert db_session.query(CandidateProfile).filter(CandidateProfile.document_id == doc.id).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cv_ingestion.py -k upsert_candidate_profile -v`
Expected: FAIL — `ImportError: cannot import name 'upsert_candidate_profile'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to backend/cv_extraction.py
def upsert_candidate_profile(db, document_id, company_id, folder_id, profile, model_id, status="done"):
    """Insert a CandidateProfile for ``document_id`` if none exists yet.

    Returns True if a row was created, False if one already existed (idempotent skip).
    Caller is responsible for committing the surrounding transaction.
    """
    from database import CandidateProfile

    exists = db.query(CandidateProfile.id).filter(CandidateProfile.document_id == document_id).first()
    if exists:
        return False

    row = CandidateProfile(
        document_id=document_id,
        company_id=company_id,
        folder_id=folder_id,
        full_name=profile.get("full_name"),
        current_title=profile.get("current_title"),
        location=profile.get("location"),
        seniority=profile.get("seniority"),
        years_experience=profile.get("years_experience"),
        skills=profile.get("skills") or [],
        languages=profile.get("languages") or [],
        education_level=profile.get("education_level"),
        last_company=profile.get("last_company"),
        raw_extraction=profile.get("raw_extraction") or {},
        extraction_status=status,
        extraction_model=model_id,
    )
    db.add(row)
    db.flush()
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cv_ingestion.py -k upsert_candidate_profile -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/cv_extraction.py backend/tests/test_cv_ingestion.py
git commit -m "feat(cv): idempotent candidate profile upsert"
```

---

## Task 9: Wire extraction into the company-RAG import callback

**Files:**
- Modify: `backend/routers/company_rag.py:444-447` (`ingest_file` inside `_company_folder_import_with_db`)
- Test: `backend/tests/test_cv_ingestion.py` (DB + mocked LLM/embeddings)

The existing `ingest_file` calls `process_document_for_user(...)` and discards the return; we now (a) capture the returned `document_id`, and (b) if the *destination folder* is a CV base, run extraction + upsert. The folder's `is_cv_base` is resolved from the `folder_id` the callback receives.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_cv_ingestion.py
import routers.company_rag as company_rag


def test_ingest_file_extracts_when_cv_base(db_session, test_user, monkeypatch):
    folder = CompanyFolder(company_id=test_user.company_id, name="CVs", is_cv_base=True)
    db_session.add(folder)
    db_session.flush()

    # Stub the heavy bits: document ingestion returns a doc id; extraction returns a profile.
    doc = Document(filename="a.pdf", content="x", user_id=test_user.id,
                   company_id=test_user.company_id, is_company_rag=True, folder_id=folder.id)
    db_session.add(doc)
    db_session.flush()

    # Accept the dummy bytes as a supported file (real validators reject non-PDF bytes).
    monkeypatch.setattr(company_rag, "validate_file_extension", lambda fn: True)
    monkeypatch.setattr(company_rag, "validate_file_content", lambda content, fn: True)
    monkeypatch.setattr(company_rag, "process_document_for_user", lambda *a, **k: doc.id)
    monkeypatch.setattr(
        company_rag, "extract_cv_metadata",
        lambda text, model_id=None: {"full_name": "Bob", "skills": ["python"], "languages": [],
                                     "years_experience": 3, "raw_extraction": {}},
    )

    summary = company_rag._company_folder_import_with_db(
        task_id="t1", company_id=test_user.company_id, user_id=test_user.id,
        destination_parent_id=folder.id,
        items=[("a.pdf", "a.pdf", b"PDFBYTES")], db=db_session,
    )

    assert summary["done"] == 1
    prof = db_session.query(CandidateProfile).filter(CandidateProfile.document_id == doc.id).first()
    assert prof is not None and prof.full_name == "Bob"


def test_ingest_file_skips_extraction_when_not_cv_base(db_session, test_user, monkeypatch):
    folder = CompanyFolder(company_id=test_user.company_id, name="Docs", is_cv_base=False)
    db_session.add(folder)
    db_session.flush()
    doc = Document(filename="b.pdf", content="x", user_id=test_user.id,
                   company_id=test_user.company_id, is_company_rag=True, folder_id=folder.id)
    db_session.add(doc)
    db_session.flush()

    called = {"extract": 0}
    monkeypatch.setattr(company_rag, "validate_file_extension", lambda fn: True)
    monkeypatch.setattr(company_rag, "validate_file_content", lambda content, fn: True)
    monkeypatch.setattr(company_rag, "process_document_for_user", lambda *a, **k: doc.id)

    def _extract(*a, **k):
        called["extract"] += 1
        return {}

    monkeypatch.setattr(company_rag, "extract_cv_metadata", _extract)

    company_rag._company_folder_import_with_db(
        task_id="t2", company_id=test_user.company_id, user_id=test_user.id,
        destination_parent_id=folder.id, items=[("b.pdf", "b.pdf", b"X")], db=db_session,
    )
    assert called["extract"] == 0
    assert db_session.query(CandidateProfile).filter(CandidateProfile.document_id == doc.id).count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cv_ingestion.py -k ingest_file -v`
Expected: FAIL — extraction not wired (`CandidateProfile` not created / `AttributeError` on `extract_cv_metadata` import in module).

- [ ] **Step 3: Write minimal implementation**

Add imports at the top of `backend/routers/company_rag.py` (with the other imports):

```python
from cv_extraction import extract_cv_metadata, upsert_candidate_profile
```

Add a module-level default model constant near the top of the file (after imports):

```python
# Default small model for CV metadata extraction (Phase 1; tune via POC, see spec §8).
CV_EXTRACTION_MODEL = "gpt-4o-mini"
```

Replace the `ingest_file` callback (`company_rag.py:444-447`) with:

```python
    def _folder_is_cv_base(folder_id):
        if folder_id is None:
            return False
        row = db.query(CompanyFolder.is_cv_base).filter(CompanyFolder.id == folder_id).first()
        return bool(row[0]) if row else False

    def ingest_file(filename, content, folder_id):
        document_id = process_document_for_user(
            filename, content, user_id, db, company_id=company_id, is_company_rag=True, folder_id=folder_id
        )
        if document_id and _folder_is_cv_base(folder_id):
            text_content = (
                db.query(Document.content).filter(Document.id == document_id).scalar() or ""
            )
            try:
                profile = extract_cv_metadata(text_content, model_id=CV_EXTRACTION_MODEL)
                upsert_candidate_profile(
                    db, document_id=document_id, company_id=company_id, folder_id=folder_id,
                    profile=profile, model_id=CV_EXTRACTION_MODEL, status="done",
                )
            except Exception as e:
                logger.warning(f"CV extraction failed for {filename}: {e}")
                upsert_candidate_profile(
                    db, document_id=document_id, company_id=company_id, folder_id=folder_id,
                    profile={"raw_extraction": {}}, model_id=CV_EXTRACTION_MODEL, status="failed",
                )
            db.commit()
```

Confirm `CompanyFolder`, `Document`, and `logger` are already imported in `company_rag.py` (they are used elsewhere in the file); if `logger` is absent, add `logger = logging.getLogger(__name__)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cv_ingestion.py -k ingest_file -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/routers/company_rag.py backend/tests/test_cv_ingestion.py
git commit -m "feat(cv): extract candidate metadata during company folder import"
```

---

## Task 10: Raise the import file cap for CV-base destinations

**Files:**
- Modify: `backend/routers/company_rag.py` (the `MAX_IMPORT_FILES` guard in `import_company_folder`, ~line 491)
- Test: `backend/tests/test_cv_ingestion.py` (pure helper, no DB needed for the resolver)

The endpoint rejects > `MAX_IMPORT_FILES` (200) before knowing the destination. For a CV-base destination folder, raise the cap to a CV-specific limit. Extract the decision into a tiny pure helper so it is unit-testable, then use it in the endpoint.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_cv_ingestion.py
from routers.company_rag import resolve_import_file_cap, MAX_IMPORT_FILES, MAX_CV_IMPORT_FILES


def test_resolve_import_file_cap():
    assert resolve_import_file_cap(is_cv_base=False) == MAX_IMPORT_FILES
    assert resolve_import_file_cap(is_cv_base=True) == MAX_CV_IMPORT_FILES
    assert MAX_CV_IMPORT_FILES > MAX_IMPORT_FILES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cv_ingestion.py -k import_file_cap -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_import_file_cap'`

- [ ] **Step 3: Write minimal implementation**

Add near the top of `backend/routers/company_rag.py` (after the existing imports / the `CV_EXTRACTION_MODEL` constant):

```python
# CV bases legitimately contain far more files than an interactive folder import.
MAX_CV_IMPORT_FILES = 5000


def resolve_import_file_cap(is_cv_base: bool) -> int:
    """Per-destination file cap: CV-base folders allow a much larger bulk import."""
    return MAX_CV_IMPORT_FILES if is_cv_base else MAX_IMPORT_FILES
```

In `import_company_folder` (`company_rag.py` ~line 488), AFTER `dest_parent_id` is resolved (the block ending ~line 499) and BEFORE the `len(files) > MAX_IMPORT_FILES` check, compute the destination's `is_cv_base` and use the resolved cap:

```python
    dest_is_cv_base = False
    if dest_parent_id is not None:
        row = db.query(CompanyFolder.is_cv_base).filter(
            CompanyFolder.id == dest_parent_id, CompanyFolder.company_id == company_id
        ).first()
        dest_is_cv_base = bool(row[0]) if row else False
    file_cap = resolve_import_file_cap(dest_is_cv_base)
    if len(files) > file_cap:
        raise HTTPException(status_code=413, detail=f"Too many files (max {file_cap})")
```

Then DELETE the original `if len(files) > MAX_IMPORT_FILES:` guard (the two lines at ~491-492) so the cap is enforced only once, by the new block.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_cv_ingestion.py -k import_file_cap -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routers/company_rag.py backend/tests/test_cv_ingestion.py
git commit -m "feat(cv): raise folder-import file cap for CV-base folders"
```

---

## Final verification

- [ ] **Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all green (CV DB tests run only when `DATABASE_URL` points at a real Postgres, matching CI).

- [ ] **Run the linter (matches CI)**

Run: `cd backend && python -m ruff check .`
Expected: no errors on the new/modified files.

---

## Phase 1 exit: POC (manual, not code)

Per spec §6.4/§8, before any full run:

1. Create a company folder, set `is_cv_base = True` on it.
2. Import **500–1000 real CVs** into it via `POST /api/company-rag/folders/import` (admin).
3. Inspect `candidate_profiles`: extraction quality (`full_name`, `skills`, `years_experience` fill rate), `extraction_status='failed'` rate, and measure real LLM + embedding cost.
4. Decide the extraction model (`CV_EXTRACTION_MODEL`) from the cost/quality trade-off, and confirm the bulk **source** (GCS prefix vs Drive) with the client before scaling to 80k.

This gives the Go/No-Go data for the full ingestion and feeds the Phase 2–4 plans (sourcing / analytics / Q&A query tools).
