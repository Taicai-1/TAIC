# Monitoring Routines — Design Spec

## Goal

4 automated monitoring routines that run daily at 9h CET, collect health/CI/security/billing data, store results in PostgreSQL, and expose them via a frontend dashboard. Later, a MCP server will let Claude Max read these reports.

## Phase 1: Backend + Frontend (this spec)

### New DB Model: `RoutineReport`

Table `routine_reports`:

| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | Auto-increment |
| type | String(20) | `health`, `ci_cd`, `security`, `billing` |
| status | String(10) | `pass`, `warn`, `fail` |
| data | JSON | Full structured report (see per-routine schemas below) |
| summary | Text | One-line human-readable summary |
| created_at | DateTime | UTC timestamp |

Index on `(type, created_at DESC)` for fast latest-by-type queries.

### New Router: `backend/routers/routines.py`

All endpoints require admin role.

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/admin/routine/run-all` | Execute all 4 routines, store results, return summary |
| POST | `/api/admin/routine/run/{type}` | Execute a single routine by type |
| GET | `/api/admin/routine/latest` | Latest report for each type (4 items max) |
| GET | `/api/admin/routine/reports` | Paginated list, filterable by `type` and `date_from`/`date_to` |
| GET | `/api/admin/routine/reports/{id}` | Full detail of one report |

### New Module: `backend/routines/`

Package with one file per routine + orchestrator:

```
backend/routines/
    __init__.py
    runner.py          # orchestrator: run_all(), run_one(type)
    health.py          # Routine 1
    ci_cd.py           # Routine 2
    security.py        # Routine 3
    billing.py         # Routine 4
```

#### Routine 1: Health (`health.py`)

Reuses internal functions from `monitoring.py`:
- `_collect_metrics()` — uptime, memory, DB pool, Redis, request latency percentiles
- `_collect_app_stats(db)` — entity counts, 24h/7d activity
- `_collect_errors()` — recent error ring buffer

Scoring:
- DB pool utilization > 70% → WARN
- Redis down → WARN
- p95 latency > 500ms → WARN
- p99 latency > 2000ms → FAIL
- Recent errors > 10 → WARN
- Any FAIL → overall FAIL, else any WARN → overall WARN, else PASS

Output schema:
```json
{
  "db": { "status": "up", "latency_ms": 7.9, "pool_utilization": 0.33 },
  "redis": { "status": "up", "latency_ms": 3.1 },
  "latency": { "p50": 45, "p90": 120, "p95": 200, "p99": 800 },
  "errors": { "count": 3, "recent": [...] },
  "app_stats": { "users": 42, "agents": 15, "documents": 230 },
  "checks": [
    { "name": "db_pool", "status": "pass", "detail": "33% utilization" },
    { "name": "redis", "status": "pass", "detail": "up, 3.1ms" },
    ...
  ]
}
```

#### Routine 2: CI/CD (`ci_cd.py`)

**GitHub Actions:**
- HTTP call to `https://api.github.com/repos/{owner}/{repo}/actions/runs?per_page=5`
- Auth via `GITHUB_TOKEN` env var (fine-grained PAT with `actions:read` scope)
- Extract: last run conclusion, name, created_at, URL
- Scoring: last run `success` → PASS, `failure` → FAIL, `in_progress` → WARN

**Cloud Build:**
- Uses `google-cloud-build` client library (add to requirements.txt)
- List recent builds for project, extract last build status, duration, trigger
- Scoring: last build `SUCCESS` → PASS, `FAILURE` → FAIL, `WORKING` → WARN

Output schema:
```json
{
  "github_actions": {
    "last_run": { "name": "CI", "conclusion": "success", "created_at": "...", "url": "..." },
    "recent_runs": [...]
  },
  "cloud_build": {
    "last_build": { "status": "SUCCESS", "duration": "120s", "trigger": "push to dev", "id": "..." },
    "recent_builds": [...]
  },
  "checks": [
    { "name": "github_ci", "status": "pass", "detail": "CI: success (2h ago)" },
    { "name": "cloud_build", "status": "pass", "detail": "Last build succeeded" }
  ]
}
```

**New env vars needed:** `GITHUB_TOKEN`, `GITHUB_REPO` (format: `owner/repo`)

#### Routine 3: Security (`security.py`)

Static analysis of the code running in the container. No git clone needed — source files are baked into the Docker image.

Checks (same as health-check command but automated):

1. **CORS config** — Parse `main.py`, verify localhost only in dev mode, no wildcards
2. **Security headers** — Count 7 required headers in middleware
3. **Hardcoded secrets** — Regex scan `backend/` for API key patterns
4. **Admin endpoint protection** — Verify all `/api/admin/` routes have `require_role`
5. **Rate limiting** — Verify 6 categories exist
6. **JWT validation** — Verify `get_jwt_secret()` raises on missing secret
7. **SQL injection patterns** — Scan for `text(f"` with user input interpolation
8. **Dependency pinning** — Count pinned vs unpinned in `requirements.txt`

Scoring:
- Any hardcoded secret → FAIL
- Unprotected admin endpoint → FAIL
- < 50% deps pinned → WARN
- Missing rate limit category → WARN
- Else PASS

The analysis reads source files from the container filesystem using standard `open()` and regex. Files to scan: `main.py`, `auth.py`, `requirements.txt`, `routers/*.py`, `helpers/rate_limiting.py`.

Output schema:
```json
{
  "checks": [
    { "name": "cors", "status": "pass", "detail": "Localhost only in dev" },
    { "name": "security_headers", "status": "pass", "detail": "7/7" },
    { "name": "hardcoded_secrets", "status": "pass", "detail": "None found" },
    { "name": "admin_protection", "status": "pass", "detail": "All 4 routes protected" },
    { "name": "rate_limiting", "status": "pass", "detail": "6/6 categories" },
    { "name": "jwt_validation", "status": "pass", "detail": "Raises RuntimeError" },
    { "name": "sql_injection", "status": "warn", "detail": "4 f-string SQL in database.py (int-cast mitigated)" },
    { "name": "dependency_pinning", "status": "fail", "detail": "0/39 pinned" }
  ]
}
```

#### Routine 4: Billing (`billing.py`)

Uses Cloud Billing Budgets API or BigQuery billing export.

**Approach: BigQuery billing export** (more reliable than Budgets API for cost reads):
- Requires billing export to BigQuery (standard GCP setup)
- Queries `project.dataset.gcp_billing_export_v1_*` for last 7 and 30 days
- Groups by service for top-5 cost breakdown

**Fallback: Cloud Billing API** if BigQuery export not configured:
- `google-cloud-billing` client
- `budgets.list()` for active budgets and spend-to-date

Scoring:
- 30d cost increase > 20% over previous 30d → WARN
- 7d cost increase > 50% over previous 7d → FAIL (spike detection)
- API unavailable → WARN with "billing data unavailable"

**New env vars needed:** `GCP_PROJECT_ID`, `BILLING_DATASET` (optional, for BigQuery)
**New dependency:** `google-cloud-billing` (add to requirements.txt)

Output schema:
```json
{
  "cost_7d": { "total": 12.50, "currency": "EUR", "top_services": [...] },
  "cost_30d": { "total": 45.20, "currency": "EUR", "top_services": [...] },
  "trend": { "7d_vs_prev_7d": "+5%", "30d_vs_prev_30d": "+12%" },
  "checks": [
    { "name": "cost_trend_7d", "status": "pass", "detail": "+5% vs previous week" },
    { "name": "cost_trend_30d", "status": "pass", "detail": "+12% vs previous month" }
  ]
}
```

### Scheduling: Cloud Scheduler

A Cloud Scheduler job hits `POST /api/admin/routine/run-all` at 9h CET daily.

Auth: OIDC token with the Cloud Run service's service account. Cloud Scheduler natively supports this — no extra secrets needed.

Config (added to `cloudbuild.yaml` and `cloudbuild_dev.yaml` as a deploy step, or manual `gcloud` setup):
```
gcloud scheduler jobs create http taic-daily-routine \
  --schedule="0 9 * * *" \
  --time-zone="Europe/Paris" \
  --uri="https://<backend-url>/api/admin/routine/run-all" \
  --http-method=POST \
  --oidc-service-account-email=<service-account>@<project>.iam.gserviceaccount.com \
  --oidc-token-audience=https://<backend-url>
```

The `run-all` endpoint will need to accept both admin-user auth (for manual triggers from dashboard) AND OIDC service account auth (for Cloud Scheduler). We add a check: if the request has a valid OIDC token from the known service account, bypass `require_role` and proceed.

### Frontend: Dashboard Page

New page: `frontend/pages/admin/monitoring.js`

Layout:
- 4 status cards at the top (one per routine type), each showing:
  - Routine name + icon
  - Last status badge (PASS green / WARN yellow / FAIL red)
  - Last run timestamp ("il y a 2h")
  - Number of checks pass/warn/fail
- Click a card → expands to show full check details
- Below cards: history table with date, type, status, summary (paginated)
- "Run now" button triggers `POST /api/admin/routine/run-all` manually

Access: Protected behind admin role check (same as existing monitoring endpoints).

### New Dependencies

Add to `backend/requirements.txt`:
- `google-cloud-billing`
- `google-cloud-build`

### New Environment Variables

| Variable | Purpose | Required |
|----------|---------|----------|
| `GITHUB_TOKEN` | GitHub API access for CI/CD status | Yes (for CI routine) |
| `GITHUB_REPO` | Format `owner/repo` | Yes (for CI routine) |
| `GCP_PROJECT_ID` | GCP project for billing/build queries | Yes |
| `BILLING_DATASET` | BigQuery dataset for billing export | No (fallback to Billing API) |

### Alembic Migration

New migration to create `routine_reports` table with the JSON column and index.

## Phase 2: MCP Server (future spec)

A lightweight MCP server that exposes `routine/latest` and `routine/reports` as tools for Claude Max. Will be designed separately once Phase 1 is deployed and generating data.

## Out of Scope

- Email/Slack notifications (can be added later as a separate routine action)
- Alerting thresholds configuration UI (hardcoded for now, configurable later)
- Multi-environment support (dev vs prod in same dashboard — each environment runs its own routines)
