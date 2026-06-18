# Rollback playbook (Cloud Run)

Cloud Run keeps previous revisions, so a bad deploy can be rolled back in one
command by shifting 100% traffic back to the last-good revision. **No rebuild.**

## Backend (prod)

```bash
# 1. List recent revisions (newest first)
gcloud run revisions list --service=applydi-backend --region=europe-west1 --limit=5

# 2. Pick the last-good revision name, then shift all traffic to it
PREV=applydi-backend-XXXXX-yyy
gcloud run services update-traffic applydi-backend --region=europe-west1 --to-revisions="$PREV=100"

# 3. Confirm
gcloud run services describe applydi-backend --region=europe-west1 \
  --format='value(status.traffic)'
```

Frontend: same commands with `applydi-frontend`.
Dev env: `dev-taic-backend` / `dev-taic-frontend`.

## Important constraints

- **Code must stay N-1 compatible across a release.** Never ship a destructive
  schema change (`DROP COLUMN`, renamed/removed table) in the SAME release as the
  code that stops using it — otherwise rolling back the code hits a schema that
  no longer matches. Do destructive removals one release LATER (expand →
  migrate → contract).
- **A bad Alembic migration is NOT auto-undone by a traffic rollback.** Down-
  migrations on live prod data are risky; prefer a forward-fix migration. The
  WS3 advisory lock (`migration_lock`) prevents concurrent-migration corruption
  but does not revert a logically-wrong migration.
- After rollback, the bad revision still exists; investigate before redeploying.

## Pre-release checklist (the eventual dev→main launch release)

1. CI green on `dev` (all 3 jobs).
2. Note the current prod revision name (your rollback target) BEFORE deploying.
3. Deploy; watch startup logs for `migration_lock: acquired` and
   `Database initialization completed successfully`.
4. Smoke-test the core flows (WS5 checklist).
5. If anything is wrong → run the rollback above immediately.
