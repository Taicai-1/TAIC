# WS1 — Tenant Isolation Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Postgres Row-Level Security (RLS) tenant isolation deterministic and idempotent at startup, close the inert/missing-RLS gaps confirmed on prod (`recaps`, `recap_documents`, `drive_links`), cover future tables (`agent_templates`, `company_folders`), stop the tenant middleware from failing silently, and prove all of it with tests.

**Architecture:** A single canonical `TENANT_TABLES` constant in `database.py` drives both RLS setup (`ensure_rls_policies`) and the company-deletion teardown (`delete_company`). `ensure_rls_policies` becomes fully self-sufficient: for every tenant table it runs `ENABLE`/`FORCE ROW LEVEL SECURITY` and creates both the `service_bypass` and `tenant_isolation` policies idempotently — instead of assuming they were created out-of-band. The tenant middleware logs resolution failures instead of swallowing them.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, PostgreSQL 15 (RLS), pytest (PG-backed tests run in CI via the `pgvector/pgvector:pg15` service).

**Verified prod state (2026-06-17):** App role `applydiuser` has `rolsuper=false, rolbypassrls=false` (RLS is enforced). 10 core tables are `enabled+forced` with 2 policies. `recaps`/`recap_documents` have 1 inert policy and RLS disabled. `drive_links` has none. `agent_templates`/`company_folders`/`missions*`/`questionnaires*` do not yet exist in prod.

---

## File Structure

- **Modify** `backend/database.py`
  - Add module-level `TENANT_TABLES` constant (canonical list of RLS-protected tables).
  - Rewrite `ensure_rls_policies()` to enable+force RLS and create both policies idempotently for every table in `TENANT_TABLES`.
- **Modify** `backend/routers/organization.py`
  - `delete_company()`: iterate `TENANT_TABLES` with per-table error tolerance (DRY + covers recaps/drive_links).
  - Share endpoints: add defense-in-depth `company_id` checks.
- **Modify** `backend/main.py`
  - `tenant_isolation_middleware`: log resolution failures (no silent `except: pass`).
- **Create** `backend/tests/test_rls_isolation.py`
  - Prove every `TENANT_TABLES` entry is `enabled+forced` with both policies after `ensure_rls_policies()` runs.

> Note: `missions*` and `questionnaires*` remain intentionally OUT of `TENANT_TABLES` (public/scheduler flows rely on app-level isolation — documented in code). They are not touched by this plan beyond existing behavior.

---

## Task 1: Canonical `TENANT_TABLES` constant

**Files:**
- Modify: `backend/database.py` (insert constant just above `def ensure_rls_policies` at line 1165)

- [ ] **Step 1: Add the constant**

Insert immediately before `def ensure_rls_policies():` (currently line 1165):

```python
# Canonical list of tenant-scoped tables protected by Postgres RLS.
# Single source of truth for ensure_rls_policies() and delete_company().
# NOTE: missions*/questionnaires* are intentionally EXCLUDED — their public
# token endpoints and background scheduler write without an app.company_id
# session var, so they use stricter app-level isolation instead (see the
# comments inside ensure_rls_policies for the full rationale).
TENANT_TABLES = [
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
    "drive_links",
    "agent_templates",
    "company_folders",
]
```

- [ ] **Step 2: Verify import-time syntax**

Run: `cd backend && python -c "import database; print(len(database.TENANT_TABLES))"`
Expected: `15` (no import error)

- [ ] **Step 3: Commit**

```bash
git add backend/database.py
git commit -m "refactor(rls): add canonical TENANT_TABLES constant"
```

---

## Task 2: Make `ensure_rls_policies()` deterministic & idempotent

**Files:**
- Modify: `backend/database.py` (`ensure_rls_policies`, currently lines 1165-1263)

**Why:** The current function only creates `service_bypass` and conditionally fixes `tenant_isolation`; it never enables RLS or creates `tenant_isolation` for new tables. That is why `recaps`/`recap_documents` have an inert policy and `drive_links` has none.

- [ ] **Step 1: Write the failing test first** (full test in Task 3 — write Task 3's file now, run it, watch it fail because `recaps` is not enabled). Skip ahead to Task 3 Steps 1-2, then return here.

- [ ] **Step 2: Replace the function body**

Replace the entire `ensure_rls_policies` function (from `def ensure_rls_policies():` through its trailing `except Exception as e: print(f"ensure_rls_policies failed: {e}", flush=True)`) with:

```python
def ensure_rls_policies():
    """Idempotently enforce RLS on every TENANT_TABLES table.

    For each table:
      1. ENABLE + FORCE ROW LEVEL SECURITY (no-op if already set).
      2. Create the 'service_bypass' SELECT policy if missing.
      3. Create/repair the 'tenant_isolation' policy (USING + WITH CHECK with
         NULLIF to tolerate an empty app.company_id session var).

    Safe to run on every instance at startup; per-table failures (e.g. a table
    that does not exist yet) are logged and skipped, never fatal.
    """
    iso_qual = "company_id = NULLIF(current_setting('app.company_id', true), '')::int"
    try:
        with engine.connect() as conn:
            conn.execute(text("SET lock_timeout = '5s'"))
            for table in TENANT_TABLES:
                try:
                    conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
                    conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))

                    # service_bypass (SELECT-only escape hatch for background jobs)
                    sb = conn.execute(
                        text(
                            "SELECT 1 FROM pg_policy "
                            "WHERE polname = 'service_bypass' AND polrelid = :t::regclass"
                        ),
                        {"t": table},
                    ).first()
                    if sb is None:
                        conn.execute(
                            text(
                                f"CREATE POLICY service_bypass ON {table} "
                                "FOR SELECT USING (current_setting('app.service_bypass', true) = 'true')"
                            )
                        )

                    # tenant_isolation — create if missing OR repair if it lacks NULLIF
                    row = conn.execute(
                        text(
                            "SELECT polqual::text FROM pg_policy "
                            "WHERE polname = 'tenant_isolation' AND polrelid = :t::regclass"
                        ),
                        {"t": table},
                    ).first()
                    needs_create = row is None or "nullif" not in (row[0] or "").lower()
                    if needs_create:
                        conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
                        conn.execute(
                            text(
                                f"CREATE POLICY tenant_isolation ON {table} "
                                f"USING ({iso_qual}) WITH CHECK ({iso_qual})"
                            )
                        )
                    conn.commit()
                    print(f"ensure_rls_policies: {table} enforced", flush=True)
                except Exception as e:
                    conn.rollback()
                    print(f"ensure_rls_policies: {table} skipped: {e}", flush=True)
        print("ensure_rls_policies completed", flush=True)
    except Exception as e:
        print(f"ensure_rls_policies failed: {e}", flush=True)
```

- [ ] **Step 3: Run the Task 3 test — expect PASS**

Run: `cd backend && python -m pytest tests/test_rls_isolation.py -v`
Expected (with PG available): PASS. (Without PG locally: SKIPPED — that's fine; it runs in CI.)

- [ ] **Step 4: Run the full suite to confirm no regression**

Run: `cd backend && python -m pytest -q`
Expected: same pass count as before + the new test (passed or skipped); 0 failures.

- [ ] **Step 5: Commit**

```bash
git add backend/database.py
git commit -m "fix(rls): enable+force RLS and create both policies idempotently for all tenant tables"
```

---

## Task 3: Test proving RLS state for every tenant table

**Files:**
- Create: `backend/tests/test_rls_isolation.py`

- [ ] **Step 1: Write the test**

```python
"""Proof that ensure_rls_policies() enforces RLS on every tenant table.

PG-backed: skips when PostgreSQL is unavailable (e.g. local without Docker);
runs in CI against the pgvector service.
"""

import pytest
from sqlalchemy import text

from tests.conftest import _db_available, _test_engine
from database import TENANT_TABLES, ensure_rls_policies


@pytest.fixture(scope="module")
def rls_applied():
    if not _db_available:
        pytest.skip("PostgreSQL not available")
    # ensure_rls_policies uses the module-level `engine`; point it at the test engine.
    import database

    original = database.engine
    database.engine = _test_engine
    try:
        ensure_rls_policies()
        yield
    finally:
        database.engine = original


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_rls_enabled_and_forced(rls_applied, table):
    with _test_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname = :t"
            ),
            {"t": table},
        ).first()
    assert row is not None, f"table {table} missing"
    assert row[0] is True, f"RLS not enabled on {table}"
    assert row[1] is True, f"RLS not forced on {table}"


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_both_policies_present(rls_applied, table):
    with _test_engine.connect() as conn:
        names = {
            r[0]
            for r in conn.execute(
                text("SELECT polname FROM pg_policy WHERE polrelid = :t::regclass"),
                {"t": table},
            ).fetchall()
        }
    assert "service_bypass" in names, f"service_bypass missing on {table}"
    assert "tenant_isolation" in names, f"tenant_isolation missing on {table}"
```

- [ ] **Step 2: Run it BEFORE Task 2's fix — expect FAIL (or skip locally)**

Run: `cd backend && python -m pytest tests/test_rls_isolation.py -v`
Expected with PG: FAIL on `recaps`/`recap_documents`/`drive_links` (RLS not enabled). Without PG: SKIPPED.

> If running locally without PG, this step is satisfied by the skip; the real red→green proof happens in CI. Note this explicitly in the task checkpoint.

- [ ] **Step 3: (after Task 2) Re-run — expect PASS**

Run: `cd backend && python -m pytest tests/test_rls_isolation.py -v`
Expected with PG: all parametrized cases PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_rls_isolation.py
git commit -m "test(rls): assert enable+force and both policies on every tenant table"
```

---

## Task 4: Harden the tenant isolation middleware

**Files:**
- Modify: `backend/main.py` (`tenant_isolation_middleware`, lines 216-245)

**Why:** `except Exception: pass` (line 242-243) hides JWT/DB errors. SELECT is fail-closed (NULL company_id → empty result), but silent failure masks incidents and could let an authenticated user's write proceed with an unresolved tenant.

- [ ] **Step 1: Replace the except block**

Change lines 242-243:

```python
    except Exception:
        pass  # Unauthenticated requests — company_id stays None, RLS returns empty
```

to:

```python
    except pyjwt.PyJWTError:
        # Expected for unauthenticated/invalid tokens — company_id stays None,
        # RLS returns empty result sets (fail-closed).
        pass
    except Exception as exc:
        # Unexpected (e.g. DB error resolving the user). Do not crash the request,
        # but surface it: company_id stays None so RLS still fails closed.
        logger.warning("tenant_isolation_middleware: company_id resolution failed: %s", exc)
```

> `pyjwt` is imported as `import jwt as pyjwt` at line 221 inside the `try`. Move that import to the top of the function (before the outer `try`, right after the docstring) so the `except pyjwt.PyJWTError` clause can reference it. Replace line 221's `import jwt as pyjwt` accordingly — add `import jwt as pyjwt` on its own line immediately after `set_current_company_id(None)` (line 219) and remove the in-`try` import.

- [ ] **Step 2: Confirm `logger` exists in main.py**

Run: `cd backend && grep -n "^logger = \|logger = logging.getLogger" main.py`
Expected: a match (logger is defined). If not, add `logger = logging.getLogger(__name__)` near the top.

- [ ] **Step 3: Smoke-import the app**

Run: `cd backend && python -c "import main; print('ok')"`
Expected: `ok` (no import/syntax error).

- [ ] **Step 4: Run auth/endpoint tests**

Run: `cd backend && python -m pytest tests/test_endpoints_auth.py tests/test_auth.py -q`
Expected: same result as before the change (no new failures).

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "fix(security): log tenant middleware resolution failures instead of swallowing them"
```

---

## Task 5: DRY `delete_company` onto `TENANT_TABLES` (+ defense-in-depth share checks)

**Files:**
- Modify: `backend/routers/organization.py` (`delete_company` rls loop ~lines 701-744; share endpoints ~904-1077)

**Why:** `delete_company` currently lists only 10 tables (misses `recaps`/`recap_documents`/`drive_links`), so company deletion leaves stale `company_id` rows. Reusing `TENANT_TABLES` with per-table tolerance fixes that. The share endpoints lack an explicit company check (RLS on `agents` already blocks foreign agents, so this is defense-in-depth).

- [ ] **Step 1: Import the constant**

At the top of `backend/routers/organization.py`, add `TENANT_TABLES` to the existing `from database import (...)` block.

Run: `cd backend && grep -n "from database import" routers/organization.py`
Then add `TENANT_TABLES,` to that import list.

- [ ] **Step 2: Replace the local `rls_tables` list**

Replace the literal `rls_tables = [ ... ]` (lines ~701-712) with:

```python
    # Disable RLS to perform cross-tenant cleanup, then re-enable. Source of
    # truth: database.TENANT_TABLES. Per-table tolerant (a table may not exist).
    rls_tables = TENANT_TABLES
```

- [ ] **Step 3: Make the per-table DDL tolerant**

The three per-table loops (DISABLE+DROP NOT NULL ~719-721, UPDATE SET NULL ~729-730, ENABLE+FORCE ~742-744) must not abort the whole deletion if one table is missing. Wrap each loop body in `try/except` that logs and continues. Replace the disable loop:

```python
        for table in rls_tables:
            try:
                cur.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
                cur.execute(f"ALTER TABLE {table} ALTER COLUMN company_id DROP NOT NULL")
            except Exception as e:
                logger.warning(f"delete_company: disable RLS on {table} skipped: {e}")
```

the nullify loop:

```python
        for table in rls_tables:
            try:
                cur.execute(f"UPDATE {table} SET company_id = NULL WHERE company_id = %s", (company_id,))
            except Exception as e:
                logger.warning(f"delete_company: nullify {table} skipped: {e}")
```

and the re-enable loop:

```python
        for table in rls_tables:
            try:
                cur.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
                cur.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            except Exception as e:
                logger.warning(f"delete_company: re-enable RLS on {table} skipped: {e}")
```

> Note: with raw psycopg, a failed statement aborts the transaction. If these run on one connection/transaction, a skipped table would still poison the txn. Confirm at execution whether `raw` autocommits per statement; if not, set `raw.autocommit = True` for the DDL phase OR run each tolerant block on a savepoint (`cur.execute("SAVEPOINT sp")` / `ROLLBACK TO SAVEPOINT sp`). Apply savepoints if the connection is transactional.

- [ ] **Step 4: Add defense-in-depth company check to the 4 share endpoints**

In `share_agent` (after line 920), `unshare_agent` (after line 989), and the two remaining share endpoints (`put .../share/...`, `get .../shares`), immediately after the `if not agent: raise 404` guard add:

```python
    from permissions import get_user_membership

    _caller_m = get_user_membership(uid, db)
    if not _caller_m or agent.company_id != _caller_m.company_id:
        raise HTTPException(status_code=404, detail="Agent not found")
```

> `get_user_membership` is already imported locally in these handlers; reuse the existing import where present rather than re-importing.

- [ ] **Step 5: Smoke-import + run org tests**

Run: `cd backend && python -c "import routers.organization; print('ok')" && python -m pytest tests/ -q -k "organization or company or permission"`
Expected: `ok` and no new failures.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/organization.py
git commit -m "fix(rls): reuse TENANT_TABLES in delete_company + defense-in-depth company checks on share endpoints"
```

---

## Task 6: Deploy-time verification (manual, post-merge)

**Not code — a verification checkpoint for the Definition of Done.**

- [ ] **Step 1:** After WS1 merges to `dev` and CD deploys to dev, re-run the prod RLS query (§ spec) against the **dev** DB. Expected: every `TENANT_TABLES` table shows `rls_enabled=true, rls_forced=true, policies=2`.
- [ ] **Step 2:** Repeat against **prod** after the prod deploy. Capture the output as the verification note.
- [ ] **Step 3:** Confirm `recaps`, `recap_documents`, `drive_links` now show `enabled=true, forced=true, policies=2`.

---

## Self-Review (completed)

- **Spec coverage:** WS1 spec items → Task 1-2 (deterministic enable/force, recaps/recap_documents/drive_links, agent_templates/company_folders), Task 4 (middleware), Task 5 (IDOR defense-in-depth + delete_company DRY), Task 3 + Task 6 (proof). Missions/questionnaires explicitly scoped out (app-level, unchanged) — matches spec.
- **Placeholders:** none — all code blocks concrete; the two execution-time confirmations (psycopg txn behavior, exact share-endpoint line offsets) are flagged as checks, not blanks.
- **Type/name consistency:** `TENANT_TABLES`, `ensure_rls_policies`, `tenant_isolation`, `service_bypass`, `get_user_membership` used consistently across tasks.
