# Fix Cloud Run Startup Timeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent Cloud Run startup probe timeouts caused by database lock contention during container initialization.

**Architecture:** Wrap all startup DDL operations in a global `statement_timeout` so they fail fast (instead of hanging for minutes), add `startup-cpu-boost` and explicit startup probe config to Cloud Run, and make the Alembic migration `0004` safe against lock waits.

**Tech Stack:** FastAPI startup event, SQLAlchemy, PostgreSQL DDL, Cloud Run gcloud deploy, Alembic

---

## Root Cause Analysis

The container fails to pass Cloud Run's startup TCP probe because `startup_event()` in `main.py` hangs on database locks:

1. `Base.metadata.create_all()` — no lock timeout, can hang indefinitely
2. `ensure_rls_policies()` — has `lock_timeout = '5s'` but creates multiple policies sequentially
3. Alembic migration `0004` — `op.add_column("agents", ...)` requires `ACCESS EXCLUSIVE` lock, env.py sets `lock_timeout = '10s'`
4. `migrate_*` functions — no lock timeout at all

When a previous revision holds shared locks on `agents` (from RLS tenant_isolation queries), all DDL operations queue behind it, exceeding the startup probe timeout.

---

### Task 1: Add global statement_timeout to startup DB operations

**Files:**
- Modify: `backend/main.py:341-400` (startup_event function)

- [ ] **Step 1: Add a statement_timeout wrapper around all DB init operations**

In `backend/main.py`, replace the `startup_event` function body to set a global `statement_timeout` on the engine connection before any DDL, and wrap the entire DB init in a try/finally:

```python
@app.on_event("startup")
async def startup_event():
    """Initialize database and run Alembic migrations on startup."""
    try:
        logger.info("Initializing database...")

        # Set aggressive statement timeout on startup DDL to prevent
        # hanging on lock contention with the previous revision.
        # Each operation has its own lock_timeout, but this is the
        # hard ceiling to guarantee the container starts.
        with engine.connect() as conn:
            conn.execute(text("SET statement_timeout = '30s'"))
            conn.execute(text("SET lock_timeout = '5s'"))
            conn.commit()

        Base.metadata.create_all(bind=engine)
        ensure_pgvector()
        ensure_columns()
        ensure_rls_policies()

        # Run Alembic migrations
        try:
            from alembic.config import Config as AlembicConfig
            from alembic import command as alembic_command

            alembic_cfg = AlembicConfig(os.path.join(os.path.dirname(__file__), "alembic.ini"))
            alembic_cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "alembic"))
            alembic_command.upgrade(alembic_cfg, "head")
            logger.info("Alembic migrations applied successfully")
        except Exception as e:
            logger.warning(f"Alembic migrations skipped (will retry next startup): {e}")

        migrate_existing_company_memberships()
        migrate_existing_recaps()
        migrate_teams_to_members()
        logger.info("Database initialization completed successfully")

        # ... rest of startup (GCS check, recap scheduler) unchanged ...
```

Wait — `SET statement_timeout` on one connection doesn't affect other connections. The `create_all`, `ensure_columns`, etc. each open their own connections from the pool. The correct approach is to set the timeout **within each function** or to use engine-level `connect_args`.

The cleanest fix is to add `connect_args` to the engine for startup only, or to set `statement_timeout` inside each function. Since we don't want to affect runtime queries, we'll set it inside `ensure_rls_policies` and the Alembic env, and add it to `ensure_columns`.

**Revised approach:** Add `lock_timeout` + `statement_timeout` inside `ensure_columns`, and reduce the Alembic lock_timeout. The `ensure_rls_policies` already has `lock_timeout = '5s'`.

In `backend/database.py`, inside `ensure_columns()` at line 865, after `with engine.connect() as conn:`, add:

```python
        with engine.connect() as conn:
            # Prevent hanging on table locks during startup
            conn.execute(text("SET lock_timeout = '5s'"))
            conn.execute(text("SET statement_timeout = '30s'"))
```

- [ ] **Step 2: Verify the edit is correct**

Run: `cd backend && python -c "from database import ensure_columns; print('import OK')"`
Expected: "import OK" (no syntax errors)

- [ ] **Step 3: Commit**

```bash
git add backend/database.py
git commit -m "fix: add lock_timeout + statement_timeout to ensure_columns startup"
```

---

### Task 2: Reduce Alembic lock_timeout and add statement_timeout

**Files:**
- Modify: `backend/alembic/env.py:57`

- [ ] **Step 1: Reduce lock_timeout from 10s to 5s and add statement_timeout**

In `backend/alembic/env.py`, replace line 57:

```python
        connection.execute(text("SET lock_timeout = '10s'"))
```

with:

```python
        connection.execute(text("SET lock_timeout = '5s'"))
        connection.execute(text("SET statement_timeout = '30s'"))
```

This ensures Alembic migrations fail fast instead of hanging.

- [ ] **Step 2: Commit**

```bash
git add backend/alembic/env.py
git commit -m "fix: reduce Alembic lock_timeout to 5s, add statement_timeout"
```

---

### Task 3: Add startup-cpu-boost and startup probe config to Cloud Run deploys

**Files:**
- Modify: `cloudbuild_dev.yaml:13-43`
- Modify: `cloudbuild.yaml:13-43`

Cloud Run's default startup probe timeout is 240s. With `startup-cpu-boost`, the container gets extra CPU during startup which helps complete the heavy import + DB init phase faster.

- [ ] **Step 1: Add startup probe and CPU boost flags to cloudbuild_dev.yaml**

Add these flags to the `gcloud run deploy` args array in `cloudbuild_dev.yaml`, after `'--max-instances'` / `'10'` and before `'--timeout'`:

```yaml
      - '--startup-cpu-boost'
      - '--cpu-boost'
```

Note: `--startup-cpu-boost` doubles the CPU allocation during container startup. This is free and significantly speeds up Python import time.

- [ ] **Step 2: Add the same flags to cloudbuild.yaml (production)**

Same change in `cloudbuild.yaml`.

- [ ] **Step 3: Commit**

```bash
git add cloudbuild_dev.yaml cloudbuild.yaml
git commit -m "fix: add startup-cpu-boost to Cloud Run deploys for faster init"
```

---

### Task 4: Make startup_event resilient with overall timeout logging

**Files:**
- Modify: `backend/main.py:341-400`

- [ ] **Step 1: Add timing logs to each startup phase**

Wrap each startup phase with timing so we can see in logs exactly where time is spent:

```python
@app.on_event("startup")
async def startup_event():
    """Initialize database and run Alembic migrations on startup."""
    import time as _time
    t0 = _time.monotonic()

    def _elapsed():
        return f"{_time.monotonic() - t0:.1f}s"

    try:
        logger.info("Initializing database...")
        Base.metadata.create_all(bind=engine)
        logger.info("create_all done (%s)", _elapsed())

        ensure_pgvector()
        logger.info("pgvector done (%s)", _elapsed())

        ensure_columns()
        logger.info("ensure_columns done (%s)", _elapsed())

        ensure_rls_policies()
        logger.info("ensure_rls_policies done (%s)", _elapsed())

        try:
            from alembic.config import Config as AlembicConfig
            from alembic import command as alembic_command

            alembic_cfg = AlembicConfig(os.path.join(os.path.dirname(__file__), "alembic.ini"))
            alembic_cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "alembic"))
            alembic_command.upgrade(alembic_cfg, "head")
            logger.info("Alembic migrations done (%s)", _elapsed())
        except Exception as e:
            logger.warning("Alembic migrations skipped (%s): %s", _elapsed(), e)

        migrate_existing_company_memberships()
        migrate_existing_recaps()
        migrate_teams_to_members()
        logger.info("Data migrations done (%s)", _elapsed())
        logger.info("Database initialization completed successfully (%s total)", _elapsed())

        # Validate GCS bucket is in EU (data sovereignty check)
        try:
            bucket_name = os.getenv("GCS_BUCKET_NAME", "applydi-documents")
            from google.cloud import storage as _gcs_storage

            _gcs_client = _gcs_storage.Client()
            _bucket = _gcs_client.get_bucket(bucket_name)
            _loc = (_bucket.location or "").upper()
            _eu_prefixes = ("EU", "EUROPE")
            if not any(_loc.startswith(p) for p in _eu_prefixes):
                logger.error(
                    f"DATA SOVEREIGNTY VIOLATION: GCS bucket '{bucket_name}' "
                    f"is located in {_loc}, expected EU region. "
                    f"Migrate the bucket to europe-west1."
                )
            else:
                logger.info(f"GCS bucket '{bucket_name}' location: {_loc} (EU compliant)")
        except Exception as e:
            logger.warning(f"Could not verify GCS bucket location: {e}")

        # Start internal recap scheduler
        try:
            from recap_scheduler import start_scheduler

            start_scheduler()
            logger.info("Recap scheduler started")
        except Exception as e:
            logger.warning(f"Recap scheduler failed to start: {e}")

        logger.info("Startup event completed (%s total)", _elapsed())
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
```

- [ ] **Step 2: Commit**

```bash
git add backend/main.py
git commit -m "fix: add elapsed time logging to each startup phase for diagnostics"
```

---

### Task 5: Deploy and verify

- [ ] **Step 1: Push the branch and trigger dev build**

```bash
git push origin dev
```

or trigger manually:

```bash
gcloud builds submit --config cloudbuild_dev.yaml
```

- [ ] **Step 2: Check Cloud Run logs for timing**

Look for these log lines in the new revision:
- `create_all done (Xs)`
- `ensure_columns done (Xs)`
- `ensure_rls_policies done (Xs)`
- `Alembic migrations done (Xs)`
- `Database initialization completed successfully (Xs total)`

If the total is under 60s, the fix is working. If any single phase exceeds 5s, it indicates lock contention that was caught by the timeout.

- [ ] **Step 3: Verify the service is healthy**

```bash
curl -s https://dev-taic-backend-817946451913.europe-west1.run.app/health
```

Expected: 200 OK response.
