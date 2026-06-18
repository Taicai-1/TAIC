# WS3 — Deploy Safety Implementation Plan

> Execute task-by-task (superpowers:executing-plans). Mix of CODE and OPS/console actions.

**Goal:** Make the (eventual) `dev`→`main` launch release safe: no migration races when 10 instances cold-start, no DB connection exhaustion, a one-command rollback, and deploys gated behind green CI.

**Verified current state (2026-06-18):** Cloud Run `--min-instances=0 --max-instances=10`, no `--concurrency` (default 80), `--timeout=300`, region europe-west1. Startup runs `create_all` + `ensure_*` + Alembic `upgrade(head)` + data migrations (`main.py:362-394`) with **no lock**. DB pool `pool_size=3, max_overflow=10` → 10×13 = **130 conns > ~100 Cloud SQL limit**. CI (lint-backend, lint-and-build-frontend, test-backend) runs on every push but does **not gate** Cloud Build. No rollback doc.

---

## Task 1 (CODE): Advisory lock around startup migrations

**Files:** `backend/database.py` (add `migration_lock`), `backend/main.py` (wrap the migration block).

**Why:** With min=0/max=10, a traffic spike cold-starts many instances that all run `create_all`/index-creation/Alembic concurrently → lock contention / migration errors. A Postgres session-level advisory lock serializes them; idempotent migrations make all-but-the-first a fast no-op.

- [ ] **Step 1:** Add to `database.py` (near other helpers):

```python
from contextlib import contextmanager

# App-wide advisory lock id for serializing startup schema migrations.
MIGRATION_LOCK_KEY = 727274


@contextmanager
def migration_lock():
    """Serialize startup schema migrations across concurrent instances.

    statement_timeout bounds the wait so a stuck holder can't hang boot forever;
    if the lock can't be acquired we proceed anyway (migrations are idempotent).
    """
    conn = engine.connect()
    acquired = False
    try:
        try:
            conn.execute(text("SET statement_timeout = '120s'"))
            conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK_KEY})
            acquired = True
            print("migration_lock: acquired", flush=True)
        except Exception as e:
            print(f"migration_lock: not acquired, proceeding ({e})", flush=True)
        yield
    finally:
        if acquired:
            try:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK_KEY})
            except Exception:
                pass
        try:
            conn.close()
        except Exception:
            pass
```

- [ ] **Step 2:** In `main.py`, import `migration_lock` and wrap the block `Base.metadata.create_all(...)` through `logger.info("Data migrations done ...")` (lines 362-394) inside `with migration_lock():` (indent that block +4). Keep the inner Alembic try/except as-is.

- [ ] **Step 3:** Verify import + bind-param parsing locally:
`python -c "from sqlalchemy import text; print(list(text('SELECT pg_advisory_lock(:k)')._bindparams.keys()))"` → `['k']`; then `import database, main` ok (dummy env).

- [ ] **Step 4:** Run full suite (no regression). Commit `fix(deploy): advisory-lock startup migrations to serialize concurrent instances`.

> Real verification is in the dev deploy logs: look for `migration_lock: acquired` then the existing `Database initialization completed`.

---

## Task 2 (CONFIG): DB pool + concurrency in Cloud Run

**Files:** `cloudbuild.yaml`, `cloudbuild_dev.yaml`.

**Why:** 10×(3+10)=130 > ~100 Cloud SQL limit. Cap per-instance connections and per-container concurrency.

- [ ] **Step 1:** On BOTH backend `gcloud run deploy` steps add:
  - `--concurrency=20`
  - env vars `DB_POOL_SIZE=4`, `DB_MAX_OVERFLOW=4` (→ 8/instance × 10 = 80 conns, margin under 100 incl. the migration-lock connection).
  Append to the existing `--set-env-vars` (don't drop existing vars) or add a `--set-env-vars` line; verify how env vars are currently passed first.

- [ ] **Step 2:** (ops note in the plan) If Cloud SQL tier is small, confirm `max_connections`; 80 leaves margin. Document the math in the commit message.

- [ ] **Step 3:** Commit `chore(deploy): cap Cloud Run concurrency + DB pool env to stay under Cloud SQL conn limit`.

> No app-test possible; verified at deploy. Defaults in `database.py` stay (local/dev unaffected); only Cloud Run sets the smaller pool via env.

---

## Task 3 (DOC): Rollback playbook

**Files:** Create `docs/ops/rollback-playbook.md`.

- [ ] **Step 1:** Document instant rollback (Cloud Run keeps prior revisions):

```bash
# Backend (repeat with applydi-frontend / dev-* names for other svc/env)
gcloud run revisions list --service=applydi-backend --region=europe-west1 --limit=5
PREV=<previous-good-revision>
gcloud run services update-traffic applydi-backend --region=europe-west1 --to-revisions=$PREV=100
```
Include: how to identify the last-good revision, that code must stay N-1 compatible (no destructive `DROP` in the same release as the code that depends on it), and that a bad Alembic migration needs a forward-fix (down-migrations are risky on prod data).

- [ ] **Step 2:** Commit `docs(ops): Cloud Run rollback playbook`.

---

## Task 4 (OPS/console): Gate deploys behind green CI

**Files:** Create `docs/ops/ci-gating.md` (runbook; the actual switches are GitHub/GCP console settings).

- [ ] **Step 1:** Document enabling **branch protection** on `main` (and `dev`): GitHub → Settings → Branches → require status checks `lint-backend`, `lint-and-build-frontend`, `test-backend` before merge; with `gh` equivalent:
```bash
gh api -X PUT repos/Taicai-1/TAIC/branches/main/protection -f required_status_checks.strict=true \
  -f 'required_status_checks.contexts[]=test-backend' ...
```
- [ ] **Step 2:** Document gating Cloud Build CD on CI: either switch the Cloud Build trigger to fire on a release tag / after CI via the GitHub Checks integration, or move deploy into a GitHub Actions job that `needs: [test-backend, lint-backend, lint-and-build-frontend]`. Recommend the latter for a single source of truth; note it's an infra change to schedule.
- [ ] **Step 3:** Commit `docs(ops): CI-gating + branch-protection runbook`.

---

## Definition of Done
- Dev deploy logs show `migration_lock: acquired` (Task 1 works in real startup).
- Cloud Run backend shows `--concurrency=20` and the DB pool env vars (Task 2).
- Rollback playbook rehearsed once on dev (Task 3).
- Branch protection enabled on `main`/`dev` (Task 4 — owner action).

## Self-review
- Code: advisory lock (T1), pool/concurrency config (T2). Ops/doc: rollback (T3), CI-gating/branch-protection (T4) — these require console access the repo can't change, delivered as runbooks + commands.
- The `:k` bind param is followed by `)` (not `::`), so it parses correctly — unlike the WS1 `:t::regclass` bug.
