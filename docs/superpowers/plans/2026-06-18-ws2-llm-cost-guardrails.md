# WS2 — LLM Cost & Abuse Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Track every LLM call's tokens + estimated cost per tenant, and enforce spend caps (monthly per company, daily per public agent) so no client — and especially no bot hitting the public chat endpoint — can run up an unbounded OpenAI/Mistral/Gemini bill.

**Architecture:** One append-only `LLMUsageLog` table is the source of truth. A contextvar carries (company_id, user_id, agent_id) set at the request boundary. Provider clients call `record_usage(...)` right after a successful response (best-effort, never breaks the request). Cap checks run at the endpoint BEFORE the LLM call and raise 429; they SUM `LLMUsageLog` over the current period (indexed query) — no Redis sync to get wrong. Caps are env defaults with an optional per-company override column.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, PostgreSQL, tiktoken (already a dep) for token estimation where providers don't return usage.

**Design decisions (locked):**
- **Source of truth = `LLMUsageLog` DB rows.** Cap check = `SELECT COALESCE(SUM(cost_usd),0)` over the period. Cheap (indexed), always correct, degrades fine without Redis. Redis caching is a documented backlog optimization, NOT in v1.
- **`LLMUsageLog` is deliberately NOT in `TENANT_TABLES` (no RLS).** The public-agent daily-cap SUM runs with no auth/`company_id` GUC, so RLS would block it. Isolation is app-level: every read filters `company_id`/`agent_id` explicitly. (Same rationale as the documented `company_invitations`/questionnaire exceptions.)
- **Token sources:** OpenAI returns exact `response.usage`; Mistral/Gemini and all streaming paths estimate via tiktoken (`cl100k_base`). Estimates are clearly acceptable for cost-guardrail purposes.
- **Caps:** `LLM_MONTHLY_CAP_USD_DEFAULT` (per company, default 50.0) and `LLM_PUBLIC_AGENT_DAILY_CAP_USD` (per public agent, default 5.0), both env-overridable. Per-company override via nullable `Company.llm_monthly_cap_usd`.

---

## File Structure

- **Create** `backend/llm_pricing.py` — price table + `estimate_cost(model, prompt_tokens, completion_tokens) -> float`.
- **Create** `backend/llm_usage.py` — contextvar, `set_llm_context`, `record_usage`, `check_company_monthly_cap`, `check_public_agent_daily_cap`, `count_tokens`.
- **Create** `backend/tests/test_llm_pricing.py`, `backend/tests/test_llm_usage.py`.
- **Modify** `backend/database.py` — add `LLMUsageLog` model + `Company.llm_monthly_cap_usd` column + `ensure_llm_usage_table()` (raw SQL for existing DBs).
- **Modify** `backend/main.py` — call `ensure_llm_usage_table()` in startup; ensure `Company.llm_monthly_cap_usd` added via existing `ensure_columns` mechanism.
- **Modify** `backend/openai_client.py`, `mistral_client.py`, `gemini_client.py` — call `record_usage(...)` after successful responses.
- **Modify** `backend/routers/ask.py`, `backend/routers/public.py` — set context + cap check (429) before the LLM call.
- **Create** `docs/ops/cloud-billing-budget.md` — gcloud script + steps for the GCP budget alert.

---

## Task 1: Pricing module

**Files:** Create `backend/llm_pricing.py`, `backend/tests/test_llm_pricing.py`

- [ ] **Step 1: Write tests**

```python
# backend/tests/test_llm_pricing.py
from llm_pricing import estimate_cost, get_model_pricing


def test_known_model_cost():
    # gpt-4o-mini: 0.15/1M input, 0.60/1M output
    cost = estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
    assert round(cost, 4) == round(0.15 + 0.60, 4)


def test_provider_prefix_stripped():
    assert get_model_pricing("openai:gpt-4o-mini") == get_model_pricing("gpt-4o-mini")


def test_unknown_model_uses_fallback_not_zero():
    # Unknown models must NOT be free (would defeat the cap); fallback > 0.
    assert estimate_cost("totally-unknown-model", 1000, 1000) > 0


def test_zero_tokens_zero_cost():
    assert estimate_cost("gpt-4o-mini", 0, 0) == 0.0
```

- [ ] **Step 2: Run — expect failure** (`ModuleNotFoundError: llm_pricing`).
Run: `cd backend && python -m pytest tests/test_llm_pricing.py -q`

- [ ] **Step 3: Implement**

```python
# backend/llm_pricing.py
"""Per-model LLM pricing (USD per token) and cost estimation.

Prices are USD per 1 token (provider list prices / 1_000_000). Keep this list
updated as providers change pricing; an unknown model falls back to a
deliberately non-zero estimate so the spend cap never treats it as free.
"""

# USD per 1,000,000 tokens -> stored as per-token below.
_PER_M = {
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    # Mistral
    "mistral-large-latest": (2.00, 6.00),
    "mistral-small-latest": (0.20, 0.60),
    "open-mistral-nemo": (0.15, 0.15),
    # Gemini
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-1.5-flash": (0.075, 0.30),
}

# Fallback for unknown models: use a mid/high estimate so caps stay conservative.
_FALLBACK_PER_M = (5.00, 15.00)


def get_model_pricing(model: str) -> tuple[float, float]:
    """Return (input_per_token, output_per_token) USD for a model id."""
    clean = (model or "").split(":")[-1].strip()
    inp_m, out_m = _PER_M.get(clean, _FALLBACK_PER_M)
    return (inp_m / 1_000_000, out_m / 1_000_000)


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD cost for a single call."""
    inp, out = get_model_pricing(model)
    return round((prompt_tokens or 0) * inp + (completion_tokens or 0) * out, 6)
```

- [ ] **Step 4: Run — expect pass.** `python -m pytest tests/test_llm_pricing.py -q`
- [ ] **Step 5: Commit** `git commit -m "feat(cost): LLM per-model pricing + cost estimation"`

---

## Task 2: `LLMUsageLog` model + `Company` cap column + startup creation

**Files:** Modify `backend/database.py`, `backend/main.py`

- [ ] **Step 1: Add the model** in `database.py` (after the `Company` class or near other models). Note: NO RLS / not in `TENANT_TABLES` (see plan header rationale).

```python
class LLMUsageLog(Base):
    __tablename__ = "llm_usage_logs"
    __table_args__ = (
        Index("ix_llm_usage_company_created", "company_id", "created_at"),
        Index("ix_llm_usage_agent_created", "agent_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, nullable=True)  # nullable: personal users / no org
    user_id = Column(Integer, nullable=True)
    agent_id = Column(Integer, nullable=True)
    provider = Column(String(32), nullable=False)
    model = Column(String(100), nullable=False)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=False, default=0.0)
    is_public = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
```

Ensure `Index` and `Float` are imported at the top of `database.py` (check the existing `from sqlalchemy import ...` line; add `Index`, `Float` if missing).

- [ ] **Step 2: Add the per-company override column** to the `Company` class:

```python
    llm_monthly_cap_usd = Column(Float, nullable=True)  # NULL = use env default
```

- [ ] **Step 3: Add `ensure_llm_usage_table()`** in `database.py` (mirror the existing `ensure_*` raw-SQL helpers so existing prod/dev DBs get the table without Alembic):

```python
def ensure_llm_usage_table():
    """Create llm_usage_logs + Company.llm_monthly_cap_usd on existing DBs (idempotent)."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SET lock_timeout = '5s'"))
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS llm_usage_logs ("
                    "id SERIAL PRIMARY KEY, company_id INTEGER, user_id INTEGER, agent_id INTEGER, "
                    "provider VARCHAR(32) NOT NULL, model VARCHAR(100) NOT NULL, "
                    "prompt_tokens INTEGER NOT NULL DEFAULT 0, completion_tokens INTEGER NOT NULL DEFAULT 0, "
                    "cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0, is_public BOOLEAN NOT NULL DEFAULT FALSE, "
                    "created_at TIMESTAMP DEFAULT NOW())"
                )
            )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_llm_usage_company_created ON llm_usage_logs (company_id, created_at)")
            )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_llm_usage_agent_created ON llm_usage_logs (agent_id, created_at)")
            )
            conn.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS llm_monthly_cap_usd DOUBLE PRECISION"))
            conn.commit()
        print("ensure_llm_usage_table completed", flush=True)
    except Exception as e:
        print(f"ensure_llm_usage_table failed: {e}", flush=True)
```

- [ ] **Step 4: Call it at startup** in `main.py` — import `ensure_llm_usage_table` alongside the other `ensure_*` imports and call it in the startup event right after `ensure_rls_policies()` (and confirm `llm_usage_logs` is intentionally NOT added to `TENANT_TABLES`).

- [ ] **Step 5: Verify import** `DATABASE_URL=... python -c "import database, main; print('ok')"` (use the dummy-env pattern from prior tasks).
- [ ] **Step 6: Commit** `git commit -m "feat(cost): LLMUsageLog table + per-company cap column + startup creation"`

---

## Task 3: Usage recording + cap checks module

**Files:** Create `backend/llm_usage.py`, `backend/tests/test_llm_usage.py`

- [ ] **Step 1: Write tests** (PG-backed for the SUM/cap parts; pure for context/token).

```python
# backend/tests/test_llm_usage.py
import pytest
import llm_usage
from llm_usage import count_tokens, set_llm_context, get_llm_context


def test_count_tokens_nonzero():
    assert count_tokens("hello world, this is a test") > 0
    assert count_tokens("") == 0


def test_context_roundtrip():
    set_llm_context(company_id=5, user_id=7, agent_id=9, is_public=False)
    ctx = get_llm_context()
    assert ctx == {"company_id": 5, "user_id": 7, "agent_id": 9, "is_public": False}


def test_record_usage_never_raises_without_context(monkeypatch):
    # No context set + no usable DB session -> must be a silent no-op, never raise.
    set_llm_context(company_id=None, user_id=None, agent_id=None, is_public=False)
    llm_usage.record_usage("openai", "gpt-4o-mini", 10, 20)  # should not raise
```

- [ ] **Step 2: Run — expect failure.**

- [ ] **Step 3: Implement `backend/llm_usage.py`**

```python
"""Per-tenant LLM usage recording + spend-cap enforcement.

Source of truth is the llm_usage_logs table. Cap checks SUM over the current
period (indexed) — correct without Redis. record_usage is best-effort and must
never break the user's request.
"""

import logging
import os
from contextvars import ContextVar
from datetime import datetime

from fastapi import HTTPException

from database import SessionLocal, LLMUsageLog, Company
from llm_pricing import estimate_cost

logger = logging.getLogger(__name__)

_llm_ctx: ContextVar[dict] = ContextVar("llm_ctx", default={})

DEFAULT_MONTHLY_CAP = float(os.getenv("LLM_MONTHLY_CAP_USD_DEFAULT", "50"))
PUBLIC_AGENT_DAILY_CAP = float(os.getenv("LLM_PUBLIC_AGENT_DAILY_CAP_USD", "5"))


def set_llm_context(company_id=None, user_id=None, agent_id=None, is_public=False):
    _llm_ctx.set(
        {"company_id": company_id, "user_id": user_id, "agent_id": agent_id, "is_public": is_public}
    )


def get_llm_context() -> dict:
    return _llm_ctx.get({}) or {}


def count_tokens(text: str) -> int:
    if not text:
        return 0
    try:
        import tiktoken

        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:
        # Fallback heuristic: ~4 chars/token.
        return max(1, len(text) // 4)


def record_usage(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> None:
    """Best-effort: write one usage row. Never raises into the caller."""
    ctx = get_llm_context()
    db = None
    try:
        cost = estimate_cost(model, prompt_tokens, completion_tokens)
        db = SessionLocal()
        db.add(
            LLMUsageLog(
                company_id=ctx.get("company_id"),
                user_id=ctx.get("user_id"),
                agent_id=ctx.get("agent_id"),
                provider=provider,
                model=model or "unknown",
                prompt_tokens=int(prompt_tokens or 0),
                completion_tokens=int(completion_tokens or 0),
                cost_usd=cost,
                is_public=bool(ctx.get("is_public")),
            )
        )
        db.commit()
    except Exception as e:
        logger.warning("record_usage failed (non-fatal): %s", e)
        if db is not None:
            try:
                db.rollback()
            except Exception:
                pass
    finally:
        if db is not None:
            db.close()


def _month_start() -> datetime:
    now = datetime.utcnow()
    return datetime(now.year, now.month, 1)


def _day_start() -> datetime:
    now = datetime.utcnow()
    return datetime(now.year, now.month, now.day)


def _sum_cost(db, *, company_id=None, agent_id=None, since: datetime) -> float:
    from sqlalchemy import func

    q = db.query(func.coalesce(func.sum(LLMUsageLog.cost_usd), 0.0)).filter(LLMUsageLog.created_at >= since)
    if company_id is not None:
        q = q.filter(LLMUsageLog.company_id == company_id)
    if agent_id is not None:
        q = q.filter(LLMUsageLog.agent_id == agent_id)
    return float(q.scalar() or 0.0)


def check_company_monthly_cap(company_id, db) -> None:
    """Raise 429 if the company is at/over its monthly cap. No-op if company_id is None."""
    if company_id is None:
        return
    cap = DEFAULT_MONTHLY_CAP
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is not None and company.llm_monthly_cap_usd is not None:
        cap = float(company.llm_monthly_cap_usd)
    spent = _sum_cost(db, company_id=company_id, since=_month_start())
    if spent >= cap:
        raise HTTPException(
            status_code=429,
            detail="Monthly AI usage limit reached for your organization. Contact your administrator.",
        )


def check_public_agent_daily_cap(agent_id, db) -> None:
    """Raise 429 if a public agent is at/over its daily cap."""
    if agent_id is None:
        return
    spent = _sum_cost(db, agent_id=agent_id, since=_day_start())
    if spent >= PUBLIC_AGENT_DAILY_CAP:
        raise HTTPException(status_code=429, detail="This assistant has reached its daily usage limit. Try again tomorrow.")
```

- [ ] **Step 4: Add a PG-backed cap test** in `test_llm_usage.py` (mirror `test_rls_isolation.py` skip pattern using `tests.conftest`): insert two `LLMUsageLog` rows summing over the cap for a company, assert `check_company_monthly_cap` raises `HTTPException` 429; under cap → no raise. (Use `conftest._db_available` live + `db_session`.)
- [ ] **Step 5: Run pure tests pass locally; PG tests skip locally / run in CI.**
- [ ] **Step 6: Commit** `git commit -m "feat(cost): usage recording + monthly/daily spend-cap checks"`

---

## Task 4: Instrument provider clients

**Files:** Modify `backend/openai_client.py`, `backend/mistral_client.py`, `backend/gemini_client.py`

Goal: after each successful response, call `record_usage(provider, model, prompt_tokens, completion_tokens)`. Best-effort import to avoid hard coupling.

- [ ] **Step 1: OpenAI exact usage** — in `get_chat_response` (`openai_client.py:309-313`), capture usage before returning:

```python
            response = client.chat.completions.create(
                model=model, messages=messages, max_tokens=max_tokens, temperature=0.7
            )
            try:
                from llm_usage import record_usage

                u = getattr(response, "usage", None)
                record_usage("openai", model, getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0))
            except Exception:
                pass
            return response.choices[0].message.content
```

Apply the same pattern to the other OpenAI return points that have a `response` object: lines ~581 (`get_chat_response_structured`) and the streaming paths (~393, ~776) — for streaming, accumulate the streamed text and estimate with `count_tokens` (no `usage` on streams). Use `count_tokens` on the joined input messages for prompt tokens when `usage` is absent.

- [ ] **Step 2: Mistral estimate** — in `mistral_client.py` after `response.choices[0].message.content` (~line 103), estimate via tiktoken:

```python
            content = response.choices[0].message.content
            try:
                from llm_usage import record_usage, count_tokens

                prompt_text = " ".join(m.get("content", "") for m in messages if isinstance(m, dict))
                record_usage("mistral", model, count_tokens(prompt_text), count_tokens(content or ""))
            except Exception:
                pass
            return content
```

- [ ] **Step 3: Gemini estimate** — same pattern in `gemini_client.py` at its response-return point (~line 165-196), `provider="gemini"`.

- [ ] **Step 4: Verify** imports compile (`python -c "import openai_client, mistral_client, gemini_client"` with dummy env) and run the full suite — no regression.
- [ ] **Step 5: Commit** `git commit -m "feat(cost): record token usage from openai/mistral/gemini responses"`

---

## Task 5: Enforce caps at the endpoints

**Files:** Modify `backend/routers/ask.py`, `backend/routers/public.py`

- [ ] **Step 1: ask.py** — right after the rate-limit check (`ask.py:31`), once `agent`/`company_id` is known (the agent branch resolves `agent.company_id` at line ~111), set context + check the company cap before `get_answer`:

```python
        from llm_usage import set_llm_context, check_company_monthly_cap

        set_llm_context(company_id=agent.company_id, user_id=int(user_id), agent_id=request.agent_id, is_public=False)
        check_company_monthly_cap(agent.company_id, db)
```

Place the cap check on every LLM path in this handler (agent branch, team branch, no-agent branch) using the resolved company_id (team branch uses the members' company; no-agent uses `_get_caller_company_id`). For the team branch set `agent_id=None`.

- [ ] **Step 2: public.py** — before the `get_answer` call (~line 80), after the existing IP rate-limit, set context + check the public-agent daily cap:

```python
        from llm_usage import set_llm_context, check_public_agent_daily_cap

        set_llm_context(company_id=agent.company_id, user_id=None, agent_id=agent.id, is_public=True)
        check_public_agent_daily_cap(agent.id, db)
```

- [ ] **Step 3: Tests** — endpoint tests (PG-backed): seed `LLMUsageLog` over cap for a company, assert `/ask` returns 429; for a public agent over the daily cap, assert the public endpoint returns 429. Add to `tests/test_endpoints_ask.py` / a new `tests/test_public_cost_cap.py`.
- [ ] **Step 4: Run full suite** — no regression; new cap tests pass in CI.
- [ ] **Step 5: Commit** `git commit -m "feat(cost): enforce monthly company + daily public-agent spend caps (429)"`

---

## Task 6: Cloud Billing budget + alert (ops doc)

**Files:** Create `docs/ops/cloud-billing-budget.md`

- [ ] **Step 1:** Document the `gcloud billing budgets create` command (using the `google-cloud-billing-budgets` dep already present) to set a monthly GCP budget with email/Pub-Sub alert thresholds (50/90/100%), and how to find the billing account id. This is infra-level protection complementary to the per-tenant caps. Not code — a runbook step the operator runs once.
- [ ] **Step 2: Commit** `git commit -m "docs(ops): Cloud Billing budget + alert runbook"`

---

## Definition of Done

- `llm_usage_logs` rows are written for every LLM call (verify via a manual `/ask` then `SELECT count(*) FROM llm_usage_logs`).
- A company at its monthly cap and a public agent at its daily cap both get a clean 429 with no LLM call made (proven by tests).
- Full suite green in CI (PG-backed cap tests run, not skipped).
- GCP budget alert documented.

## Self-Review

- **Spec coverage:** LLMUsageLog (T2) ✓, instrumentation (T4) ✓, monthly per-tenant + daily per-public-agent caps (T3/T5) ✓, Cloud Billing budget (T6) ✓.
- **Placeholders:** integration edits in T4/T5 reference approximate line numbers (`~`) because provider/router internals shift; each step gives the anchoring code to find the spot. New modules (T1/T3) have complete code.
- **RLS consistency:** `llm_usage_logs` intentionally excluded from `TENANT_TABLES` (public daily-cap reads run without GUC); app-level company filter documented.
