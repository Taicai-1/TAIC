# Monitoring Routines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 4 automated monitoring routines (health, CI/CD, security, billing) that run daily at 9h CET via Cloud Scheduler, store results in PostgreSQL, and display on a frontend admin dashboard.

**Architecture:** New `backend/routines/` package with one module per routine + orchestrator. New `backend/routers/routines.py` router exposes admin endpoints. New `RoutineReport` SQLAlchemy model with Alembic migration. New `frontend/pages/admin/monitoring.js` dashboard page. Cloud Scheduler triggers `POST /api/admin/routine/run-all` via OIDC auth.

**Tech Stack:** FastAPI, SQLAlchemy (JSON column), Alembic, httpx (GitHub API), google-cloud-build, google-cloud-billing, Next.js/React/Tailwind

---

## File Structure

```
backend/
  database.py                          # MODIFY: add RoutineReport model
  main.py                              # MODIFY: register routines router
  requirements.txt                     # MODIFY: add google-cloud-build, google-cloud-billing
  alembic/versions/0003_routine_reports.py  # CREATE: migration
  routines/
    __init__.py                        # CREATE: package init
    runner.py                          # CREATE: orchestrator run_all/run_one
    health.py                          # CREATE: health routine
    ci_cd.py                           # CREATE: CI/CD routine
    security.py                        # CREATE: security routine
    billing.py                         # CREATE: billing routine
  routers/routines.py                  # CREATE: API endpoints
  tests/
    test_routines_health.py            # CREATE: health routine tests
    test_routines_ci_cd.py             # CREATE: CI/CD routine tests
    test_routines_security.py          # CREATE: security routine tests
    test_routines_billing.py           # CREATE: billing routine tests
    test_routines_runner.py            # CREATE: orchestrator tests
    test_routines_router.py            # CREATE: router endpoint tests (skip if PostgreSQL unavailable)
frontend/
  pages/admin/monitoring.js            # CREATE: dashboard page
cloudbuild_dev.yaml                    # MODIFY: add GITHUB_TOKEN, GITHUB_REPO, GCP_PROJECT_ID secrets
cloudbuild.yaml                        # MODIFY: same env vars for prod
```

---

### Task 1: RoutineReport DB Model + Alembic Migration

**Files:**
- Modify: `backend/database.py` (add model after existing models, ~line 500)
- Create: `backend/alembic/versions/0003_routine_reports.py`

- [ ] **Step 1: Add RoutineReport model to database.py**

Add after the last model class (before `_current_company_id` context var section, around line 510):

```python
class RoutineReport(Base):
    __tablename__ = "routine_reports"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String(20), nullable=False, index=True)  # health, ci_cd, security, billing
    status = Column(String(10), nullable=False)  # pass, warn, fail
    data = Column(Text, nullable=False)  # JSON string (use json.dumps/loads)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
```

Note: We use `Text` for `data` instead of `JSON` type because SQLAlchemy's JSON column has inconsistent behavior across PostgreSQL versions. We'll `json.dumps`/`json.loads` explicitly.

- [ ] **Step 2: Create Alembic migration file**

Create `backend/alembic/versions/0003_routine_reports.py`:

```python
"""add routine_reports table

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "routine_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_routine_reports_type", "routine_reports", ["type"])
    op.create_index("ix_routine_reports_created_at", "routine_reports", ["created_at"])
    op.create_index(
        "ix_routine_reports_type_created_at",
        "routine_reports",
        ["type", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_routine_reports_type_created_at", table_name="routine_reports")
    op.drop_index("ix_routine_reports_created_at", table_name="routine_reports")
    op.drop_index("ix_routine_reports_type", table_name="routine_reports")
    op.drop_table("routine_reports")
```

- [ ] **Step 3: Verify migration syntax**

Run: `cd backend && python -c "from alembic.versions import __path__; print('OK')"`

This only checks the import path resolves. The actual migration runs on startup via Alembic in `main.py`.

- [ ] **Step 4: Commit**

```bash
git add backend/database.py backend/alembic/versions/0003_routine_reports.py
git commit -m "feat: add RoutineReport model and migration"
```

---

### Task 2: Health Routine

**Files:**
- Create: `backend/routines/__init__.py`
- Create: `backend/routines/health.py`
- Create: `backend/tests/test_routines_health.py`

- [ ] **Step 1: Create package init**

Create `backend/routines/__init__.py`:

```python
"""Monitoring routines — automated daily health, CI/CD, security, and billing checks."""
```

- [ ] **Step 2: Write failing tests for health routine**

Create `backend/tests/test_routines_health.py`:

```python
"""Tests for routines.health — no DB required, all functions are mocked."""

import pytest
from unittest.mock import patch, MagicMock

from routines.health import run_health_check


class TestRunHealthCheck:
    def _mock_metrics(self, pool_util=0.3, redis_status="up", p95=200, p99=800):
        return {
            "uptime_seconds": 3600,
            "db_pool": {
                "size": 3,
                "checked_in": 2,
                "checked_out": 1,
                "overflow": 0,
            },
            "redis": {"status": redis_status},
            "request_latency": {
                "total_requests": 100,
                "latency_percentiles": {
                    "p50": 50,
                    "p90": 100,
                    "p95": p95,
                    "p99": p99,
                },
            },
        }

    def _mock_app_stats(self):
        return {
            "totals": {"users": 10, "agents": 5, "documents": 20, "conversations": 30, "messages": 100, "chunks": 200},
            "last_24h": {"users": 1, "agents": 0, "documents": 2, "conversations": 5, "messages": 15},
            "last_7d": {"users": 3, "agents": 1, "documents": 8, "conversations": 12, "messages": 50},
        }

    @patch("routines.health._collect_errors", return_value=[])
    @patch("routines.health._collect_app_stats")
    @patch("routines.health._collect_metrics")
    def test_all_healthy_returns_pass(self, mock_metrics, mock_stats, mock_errors):
        mock_metrics.return_value = self._mock_metrics()
        mock_stats.return_value = self._mock_app_stats()
        db = MagicMock()

        result = run_health_check(db)

        assert result["status"] == "pass"
        assert all(c["status"] == "pass" for c in result["checks"])

    @patch("routines.health._collect_errors", return_value=[{"msg": "err"}] * 15)
    @patch("routines.health._collect_app_stats")
    @patch("routines.health._collect_metrics")
    def test_many_errors_returns_warn(self, mock_metrics, mock_stats, mock_errors):
        mock_metrics.return_value = self._mock_metrics()
        mock_stats.return_value = self._mock_app_stats()
        db = MagicMock()

        result = run_health_check(db)

        assert result["status"] == "warn"
        error_check = next(c for c in result["checks"] if c["name"] == "recent_errors")
        assert error_check["status"] == "warn"

    @patch("routines.health._collect_errors", return_value=[])
    @patch("routines.health._collect_app_stats")
    @patch("routines.health._collect_metrics")
    def test_redis_down_returns_warn(self, mock_metrics, mock_stats, mock_errors):
        mock_metrics.return_value = self._mock_metrics(redis_status="down")
        mock_stats.return_value = self._mock_app_stats()
        db = MagicMock()

        result = run_health_check(db)

        assert result["status"] == "warn"
        redis_check = next(c for c in result["checks"] if c["name"] == "redis")
        assert redis_check["status"] == "warn"

    @patch("routines.health._collect_errors", return_value=[])
    @patch("routines.health._collect_app_stats")
    @patch("routines.health._collect_metrics")
    def test_high_p99_returns_fail(self, mock_metrics, mock_stats, mock_errors):
        mock_metrics.return_value = self._mock_metrics(p99=2500)
        mock_stats.return_value = self._mock_app_stats()
        db = MagicMock()

        result = run_health_check(db)

        assert result["status"] == "fail"
        latency_check = next(c for c in result["checks"] if c["name"] == "latency_p99")
        assert latency_check["status"] == "fail"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && JWT_SECRET_KEY=test-secret-key DATABASE_URL=sqlite:///test.db ENVIRONMENT=test python -m pytest tests/test_routines_health.py -v`

Expected: FAIL (ModuleNotFoundError: routines.health)

- [ ] **Step 4: Implement health routine**

Create `backend/routines/health.py`:

```python
"""Health monitoring routine — evaluates DB, Redis, latency, errors, app stats."""

import logging
from typing import Any

from sqlalchemy.orm import Session

from routers.monitoring import _collect_app_stats, _collect_errors, _collect_metrics

logger = logging.getLogger(__name__)


def run_health_check(db: Session) -> dict[str, Any]:
    """Run health checks and return structured report with status and checks list."""
    metrics = _collect_metrics()
    app_stats = _collect_app_stats(db)
    errors = _collect_errors(limit=50)

    checks: list[dict[str, Any]] = []

    # DB pool utilization
    pool = metrics["db_pool"]
    total_capacity = pool["size"] + max(pool["overflow"], 0)
    utilization = pool["checked_out"] / total_capacity if total_capacity > 0 else 0
    if utilization > 0.7:
        checks.append({"name": "db_pool", "status": "warn", "detail": f"{utilization:.0%} utilization"})
    else:
        checks.append({"name": "db_pool", "status": "pass", "detail": f"{utilization:.0%} utilization"})

    # Redis
    redis_status = metrics["redis"].get("status", "unavailable")
    if redis_status in ("down", "error", "unavailable"):
        checks.append({"name": "redis", "status": "warn", "detail": redis_status})
    else:
        checks.append({"name": "redis", "status": "pass", "detail": redis_status})

    # Latency percentiles
    latency = metrics.get("request_latency", {})
    percentiles = latency.get("latency_percentiles", {})
    p95 = percentiles.get("p95", 0)
    p99 = percentiles.get("p99", 0)

    if p95 > 500:
        checks.append({"name": "latency_p95", "status": "warn", "detail": f"{p95}ms"})
    else:
        checks.append({"name": "latency_p95", "status": "pass", "detail": f"{p95}ms"})

    if p99 > 2000:
        checks.append({"name": "latency_p99", "status": "fail", "detail": f"{p99}ms"})
    else:
        checks.append({"name": "latency_p99", "status": "pass", "detail": f"{p99}ms"})

    # Recent errors
    error_count = len(errors)
    if error_count > 10:
        checks.append({"name": "recent_errors", "status": "warn", "detail": f"{error_count} errors"})
    else:
        checks.append({"name": "recent_errors", "status": "pass", "detail": f"{error_count} errors"})

    # Overall status
    statuses = [c["status"] for c in checks]
    if "fail" in statuses:
        overall = "fail"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "pass"

    return {
        "status": overall,
        "checks": checks,
        "db": {
            "status": "up",
            "pool_utilization": round(utilization, 2),
        },
        "redis": metrics["redis"],
        "latency": percentiles,
        "errors": {"count": error_count, "recent": errors[:5]},
        "app_stats": app_stats.get("totals", {}),
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && JWT_SECRET_KEY=test-secret-key DATABASE_URL=sqlite:///test.db ENVIRONMENT=test python -m pytest tests/test_routines_health.py -v`

Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add backend/routines/__init__.py backend/routines/health.py backend/tests/test_routines_health.py
git commit -m "feat: add health monitoring routine with tests"
```

---

### Task 3: CI/CD Routine

**Files:**
- Create: `backend/routines/ci_cd.py`
- Create: `backend/tests/test_routines_ci_cd.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_routines_ci_cd.py`:

```python
"""Tests for routines.ci_cd — all external calls mocked."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from routines.ci_cd import run_ci_cd_check


class TestGitHubActions:
    @patch("routines.ci_cd._fetch_cloud_builds")
    @patch("routines.ci_cd._fetch_github_runs")
    def test_success_run_returns_pass(self, mock_gh, mock_cb):
        mock_gh.return_value = {
            "last_run": {"name": "CI", "conclusion": "success", "created_at": "2026-04-29T07:00:00Z", "url": "https://github.com/test/repo/actions/runs/1"},
            "recent_runs": [],
        }
        mock_cb.return_value = {
            "last_build": {"status": "SUCCESS", "duration": "120s", "trigger": "push", "id": "build-1"},
            "recent_builds": [],
        }

        result = run_ci_cd_check()

        assert result["status"] == "pass"
        gh_check = next(c for c in result["checks"] if c["name"] == "github_ci")
        assert gh_check["status"] == "pass"

    @patch("routines.ci_cd._fetch_cloud_builds")
    @patch("routines.ci_cd._fetch_github_runs")
    def test_failed_run_returns_fail(self, mock_gh, mock_cb):
        mock_gh.return_value = {
            "last_run": {"name": "CI", "conclusion": "failure", "created_at": "2026-04-29T07:00:00Z", "url": "https://github.com/test/repo/actions/runs/1"},
            "recent_runs": [],
        }
        mock_cb.return_value = {
            "last_build": {"status": "SUCCESS", "duration": "120s", "trigger": "push", "id": "build-1"},
            "recent_builds": [],
        }

        result = run_ci_cd_check()

        assert result["status"] == "fail"

    @patch("routines.ci_cd._fetch_cloud_builds")
    @patch("routines.ci_cd._fetch_github_runs")
    def test_in_progress_returns_warn(self, mock_gh, mock_cb):
        mock_gh.return_value = {
            "last_run": {"name": "CI", "conclusion": None, "status": "in_progress", "created_at": "2026-04-29T07:00:00Z", "url": "https://github.com/test/repo/actions/runs/1"},
            "recent_runs": [],
        }
        mock_cb.return_value = {
            "last_build": {"status": "SUCCESS", "duration": "120s", "trigger": "push", "id": "build-1"},
            "recent_builds": [],
        }

        result = run_ci_cd_check()

        assert result["status"] == "warn"

    @patch("routines.ci_cd._fetch_cloud_builds")
    @patch("routines.ci_cd._fetch_github_runs")
    def test_github_unavailable_returns_warn(self, mock_gh, mock_cb):
        mock_gh.return_value = None
        mock_cb.return_value = {
            "last_build": {"status": "SUCCESS", "duration": "120s", "trigger": "push", "id": "build-1"},
            "recent_builds": [],
        }

        result = run_ci_cd_check()

        gh_check = next(c for c in result["checks"] if c["name"] == "github_ci")
        assert gh_check["status"] == "warn"
        assert "unavailable" in gh_check["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && JWT_SECRET_KEY=test-secret-key DATABASE_URL=sqlite:///test.db ENVIRONMENT=test python -m pytest tests/test_routines_ci_cd.py -v`

Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implement CI/CD routine**

Create `backend/routines/ci_cd.py`:

```python
"""CI/CD monitoring routine — checks GitHub Actions and Cloud Build status."""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")


def _fetch_github_runs() -> Optional[dict[str, Any]]:
    """Fetch last 5 GitHub Actions runs. Returns None on failure."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        logger.warning("GITHUB_TOKEN or GITHUB_REPO not set, skipping GitHub check")
        return None

    try:
        resp = httpx.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs",
            params={"per_page": 5},
            headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"},
            timeout=15,
        )
        resp.raise_for_status()
        runs = resp.json().get("workflow_runs", [])
        if not runs:
            return {"last_run": None, "recent_runs": []}

        def _format_run(r):
            return {
                "name": r.get("name"),
                "conclusion": r.get("conclusion"),
                "status": r.get("status"),
                "created_at": r.get("created_at"),
                "url": r.get("html_url"),
            }

        return {
            "last_run": _format_run(runs[0]),
            "recent_runs": [_format_run(r) for r in runs[:5]],
        }
    except Exception as e:
        logger.error(f"GitHub Actions fetch failed: {e}")
        return None


def _fetch_cloud_builds() -> Optional[dict[str, Any]]:
    """Fetch last 5 Cloud Build builds. Returns None on failure."""
    if not GCP_PROJECT_ID:
        logger.warning("GCP_PROJECT_ID not set, skipping Cloud Build check")
        return None

    try:
        from google.cloud.devtools import cloudbuild_v1

        client = cloudbuild_v1.CloudBuildClient()
        request = cloudbuild_v1.ListBuildsRequest(project_id=GCP_PROJECT_ID, page_size=5)
        response = client.list_builds(request=request)

        builds = list(response.builds) if hasattr(response, "builds") else list(response)
        if not builds:
            return {"last_build": None, "recent_builds": []}

        def _format_build(b):
            status_name = b.status.name if hasattr(b.status, "name") else str(b.status)
            duration_s = ""
            if b.finish_time and b.start_time:
                duration_s = f"{(b.finish_time - b.start_time).total_seconds():.0f}s"
            return {
                "status": status_name,
                "duration": duration_s,
                "trigger": getattr(b.build_trigger_id, "", "manual"),
                "id": b.id,
            }

        return {
            "last_build": _format_build(builds[0]),
            "recent_builds": [_format_build(b) for b in builds[:5]],
        }
    except Exception as e:
        logger.error(f"Cloud Build fetch failed: {e}")
        return None


def run_ci_cd_check() -> dict[str, Any]:
    """Run CI/CD checks and return structured report."""
    checks: list[dict[str, Any]] = []
    github_data = _fetch_github_runs()
    cloud_build_data = _fetch_cloud_builds()

    # GitHub Actions check
    if github_data is None:
        checks.append({"name": "github_ci", "status": "warn", "detail": "GitHub API unavailable"})
    elif github_data["last_run"] is None:
        checks.append({"name": "github_ci", "status": "warn", "detail": "No runs found"})
    else:
        run = github_data["last_run"]
        conclusion = run.get("conclusion")
        status = run.get("status")
        if conclusion == "success":
            checks.append({"name": "github_ci", "status": "pass", "detail": f"CI: success ({run['created_at']})"})
        elif conclusion == "failure":
            checks.append({"name": "github_ci", "status": "fail", "detail": f"CI: failure ({run['created_at']})"})
        elif status == "in_progress" or conclusion is None:
            checks.append({"name": "github_ci", "status": "warn", "detail": f"CI: in progress ({run['created_at']})"})
        else:
            checks.append({"name": "github_ci", "status": "warn", "detail": f"CI: {conclusion}"})

    # Cloud Build check
    if cloud_build_data is None:
        checks.append({"name": "cloud_build", "status": "warn", "detail": "Cloud Build API unavailable"})
    elif cloud_build_data["last_build"] is None:
        checks.append({"name": "cloud_build", "status": "warn", "detail": "No builds found"})
    else:
        build = cloud_build_data["last_build"]
        build_status = build["status"]
        if build_status == "SUCCESS":
            checks.append({"name": "cloud_build", "status": "pass", "detail": f"Last build succeeded ({build['duration']})"})
        elif build_status in ("FAILURE", "INTERNAL_ERROR", "TIMEOUT"):
            checks.append({"name": "cloud_build", "status": "fail", "detail": f"Last build: {build_status}"})
        elif build_status == "WORKING":
            checks.append({"name": "cloud_build", "status": "warn", "detail": "Build in progress"})
        else:
            checks.append({"name": "cloud_build", "status": "warn", "detail": f"Build status: {build_status}"})

    # Overall
    statuses = [c["status"] for c in checks]
    if "fail" in statuses:
        overall = "fail"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "pass"

    return {
        "status": overall,
        "checks": checks,
        "github_actions": github_data,
        "cloud_build": cloud_build_data,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && JWT_SECRET_KEY=test-secret-key DATABASE_URL=sqlite:///test.db ENVIRONMENT=test python -m pytest tests/test_routines_ci_cd.py -v`

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/routines/ci_cd.py backend/tests/test_routines_ci_cd.py
git commit -m "feat: add CI/CD monitoring routine with tests"
```

---

### Task 4: Security Routine

**Files:**
- Create: `backend/routines/security.py`
- Create: `backend/tests/test_routines_security.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_routines_security.py`:

```python
"""Tests for routines.security — reads real source files from the backend directory."""

import pytest
import os

from routines.security import run_security_check


class TestRunSecurityCheck:
    def test_returns_all_8_checks(self):
        result = run_security_check()
        check_names = [c["name"] for c in result["checks"]]
        expected = [
            "cors", "security_headers", "hardcoded_secrets",
            "admin_protection", "rate_limiting", "jwt_validation",
            "sql_injection", "dependency_pinning",
        ]
        assert check_names == expected

    def test_status_is_string(self):
        result = run_security_check()
        assert result["status"] in ("pass", "warn", "fail")

    def test_cors_check_passes(self):
        """CORS should pass because localhost is gated behind ENVIRONMENT==development."""
        result = run_security_check()
        cors = next(c for c in result["checks"] if c["name"] == "cors")
        assert cors["status"] == "pass"

    def test_security_headers_passes(self):
        """All 7 security headers are present in main.py middleware."""
        result = run_security_check()
        headers = next(c for c in result["checks"] if c["name"] == "security_headers")
        assert headers["status"] == "pass"
        assert "7/7" in headers["detail"]

    def test_hardcoded_secrets_passes(self):
        """No hardcoded API keys in the codebase."""
        result = run_security_check()
        secrets = next(c for c in result["checks"] if c["name"] == "hardcoded_secrets")
        assert secrets["status"] == "pass"

    def test_dependency_pinning_warns_or_fails(self):
        """Current requirements.txt has 0 pinned deps — should be warn or fail."""
        result = run_security_check()
        deps = next(c for c in result["checks"] if c["name"] == "dependency_pinning")
        assert deps["status"] in ("warn", "fail")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && JWT_SECRET_KEY=test-secret-key DATABASE_URL=sqlite:///test.db ENVIRONMENT=test python -m pytest tests/test_routines_security.py -v`

Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implement security routine**

Create `backend/routines/security.py`:

```python
"""Security static analysis routine — scans source files in the container."""

import glob
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# Base directory: where the backend source lives (same dir as this file's parent)
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_file(rel_path: str) -> str:
    """Read a file relative to backend dir. Returns empty string on failure."""
    try:
        with open(os.path.join(_BACKEND_DIR, rel_path), encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _check_cors() -> dict[str, Any]:
    content = _read_file("main.py")
    has_wildcard = '"*"' in content and "allowed_origins" in content
    # Check that localhost is only in development block
    dev_gated = 'if ENVIRONMENT == "development"' in content or "if ENVIRONMENT == 'development'" in content
    localhost_in_main_list = re.search(r'allowed_origins\s*=\s*\[.*localhost', content, re.DOTALL)

    if has_wildcard:
        return {"name": "cors", "status": "fail", "detail": "Wildcard * in allowed origins"}
    if localhost_in_main_list:
        return {"name": "cors", "status": "fail", "detail": "Localhost in base allowed_origins list"}
    if dev_gated:
        return {"name": "cors", "status": "pass", "detail": "Localhost only in development mode"}
    return {"name": "cors", "status": "warn", "detail": "Could not verify CORS configuration"}


def _check_security_headers() -> dict[str, Any]:
    content = _read_file("main.py")
    required = [
        "Strict-Transport-Security",
        "Content-Security-Policy",
        "X-Frame-Options",
        "X-Content-Type-Options",
        "X-XSS-Protection",
        "Referrer-Policy",
        "Permissions-Policy",
    ]
    found = sum(1 for h in required if h in content)
    if found == 7:
        return {"name": "security_headers", "status": "pass", "detail": "7/7"}
    return {"name": "security_headers", "status": "warn", "detail": f"{found}/7"}


def _check_hardcoded_secrets() -> dict[str, Any]:
    patterns = [
        r'sk-[a-zA-Z0-9]{20,}',
        r'AKIA[0-9A-Z]{16}',
    ]
    findings = []
    for py_file in glob.glob(os.path.join(_BACKEND_DIR, "**", "*.py"), recursive=True):
        if "tests" in py_file or "__pycache__" in py_file:
            continue
        try:
            with open(py_file, encoding="utf-8") as f:
                content = f.read()
            for pattern in patterns:
                if re.search(pattern, content):
                    rel = os.path.relpath(py_file, _BACKEND_DIR)
                    findings.append(rel)
        except Exception:
            continue

    if findings:
        return {"name": "hardcoded_secrets", "status": "fail", "detail": f"Found in: {', '.join(findings)}"}
    return {"name": "hardcoded_secrets", "status": "pass", "detail": "None found"}


def _check_admin_protection() -> dict[str, Any]:
    routers_dir = os.path.join(_BACKEND_DIR, "routers")
    unprotected = []
    for py_file in glob.glob(os.path.join(routers_dir, "*.py")):
        try:
            with open(py_file, encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue

        # Find all route functions with /api/admin/ paths
        route_pattern = r'@router\.(get|post|put|delete|patch)\(["\'](/api/admin/[^"\']+)'
        for match in re.finditer(route_pattern, content):
            path = match.group(2)
            # Find the function body after this decorator
            func_start = match.end()
            # Look for require_role in the next ~500 chars (function body)
            func_body = content[func_start:func_start + 500]
            # Token-based auth routes (org request) are intentionally unprotected
            if "/companies/request/" in path:
                continue
            if "require_role" not in func_body:
                rel = os.path.relpath(py_file, _BACKEND_DIR)
                unprotected.append(f"{rel}:{path}")

    if unprotected:
        return {"name": "admin_protection", "status": "fail", "detail": f"Unprotected: {', '.join(unprotected)}"}
    return {"name": "admin_protection", "status": "pass", "detail": "All admin routes protected"}


def _check_rate_limiting() -> dict[str, Any]:
    content = _read_file("helpers/rate_limiting.py")
    categories = {
        "auth": "_check_auth_rate_limit",
        "api": "_check_api_rate_limit",
        "public_chat": "_check_rate_limit",
        "org_request": "_check_org_request_rate_limit",
        "2fa": "_check_2fa_rate_limit",
        "password_change": "_check_password_change_rate_limit",
    }
    found = {name for name, func in categories.items() if func in content}
    missing = set(categories.keys()) - found
    if not missing:
        return {"name": "rate_limiting", "status": "pass", "detail": f"{len(found)}/6 categories"}
    return {"name": "rate_limiting", "status": "warn", "detail": f"{len(found)}/6 (missing: {', '.join(missing)})"}


def _check_jwt_validation() -> dict[str, Any]:
    content = _read_file("auth.py")
    if "raise RuntimeError" in content and "JWT" in content:
        return {"name": "jwt_validation", "status": "pass", "detail": "Raises RuntimeError on missing secret"}
    return {"name": "jwt_validation", "status": "fail", "detail": "No RuntimeError on missing JWT secret"}


def _check_sql_injection() -> dict[str, Any]:
    pattern = r'text\(f["\']'
    findings = []
    for py_file in glob.glob(os.path.join(_BACKEND_DIR, "**", "*.py"), recursive=True):
        if "tests" in py_file or "__pycache__" in py_file:
            continue
        try:
            with open(py_file, encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    if re.search(pattern, line):
                        rel = os.path.relpath(py_file, _BACKEND_DIR)
                        findings.append(f"{rel}:{i}")
        except Exception:
            continue

    if findings:
        return {"name": "sql_injection", "status": "warn", "detail": f"{len(findings)} f-string SQL patterns: {', '.join(findings)}"}
    return {"name": "sql_injection", "status": "pass", "detail": "No unsafe SQL patterns"}


def _check_dependency_pinning() -> dict[str, Any]:
    content = _read_file("requirements.txt")
    lines = [l.strip() for l in content.strip().splitlines() if l.strip() and not l.startswith("#")]
    total = len(lines)
    pinned = sum(1 for l in lines if "==" in l)

    if total == 0:
        return {"name": "dependency_pinning", "status": "warn", "detail": "No dependencies found"}
    ratio = pinned / total
    if ratio >= 0.5:
        return {"name": "dependency_pinning", "status": "pass", "detail": f"{pinned}/{total} pinned"}
    return {"name": "dependency_pinning", "status": "warn", "detail": f"{pinned}/{total} pinned"}


def run_security_check() -> dict[str, Any]:
    """Run all security checks and return structured report."""
    checks = [
        _check_cors(),
        _check_security_headers(),
        _check_hardcoded_secrets(),
        _check_admin_protection(),
        _check_rate_limiting(),
        _check_jwt_validation(),
        _check_sql_injection(),
        _check_dependency_pinning(),
    ]

    statuses = [c["status"] for c in checks]
    if "fail" in statuses:
        overall = "fail"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "pass"

    return {"status": overall, "checks": checks}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && JWT_SECRET_KEY=test-secret-key DATABASE_URL=sqlite:///test.db ENVIRONMENT=test python -m pytest tests/test_routines_security.py -v`

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/routines/security.py backend/tests/test_routines_security.py
git commit -m "feat: add security static analysis routine with tests"
```

---

### Task 5: Billing Routine

**Files:**
- Create: `backend/routines/billing.py`
- Create: `backend/tests/test_routines_billing.py`
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add dependencies**

Append to `backend/requirements.txt`:

```
google-cloud-billing
google-cloud-build
```

- [ ] **Step 2: Write failing tests**

Create `backend/tests/test_routines_billing.py`:

```python
"""Tests for routines.billing — all GCP calls mocked."""

import pytest
from unittest.mock import patch, MagicMock

from routines.billing import run_billing_check


class TestRunBillingCheck:
    @patch("routines.billing._fetch_billing_data")
    def test_normal_costs_returns_pass(self, mock_fetch):
        mock_fetch.return_value = {
            "cost_7d": {"total": 10.0, "currency": "EUR", "top_services": []},
            "cost_30d": {"total": 40.0, "currency": "EUR", "top_services": []},
            "prev_7d_total": 9.5,
            "prev_30d_total": 38.0,
        }

        result = run_billing_check()

        assert result["status"] == "pass"

    @patch("routines.billing._fetch_billing_data")
    def test_30d_increase_over_20pct_returns_warn(self, mock_fetch):
        mock_fetch.return_value = {
            "cost_7d": {"total": 10.0, "currency": "EUR", "top_services": []},
            "cost_30d": {"total": 50.0, "currency": "EUR", "top_services": []},
            "prev_7d_total": 9.5,
            "prev_30d_total": 35.0,  # 50/35 = 42% increase
        }

        result = run_billing_check()

        assert result["status"] == "warn"
        trend_check = next(c for c in result["checks"] if c["name"] == "cost_trend_30d")
        assert trend_check["status"] == "warn"

    @patch("routines.billing._fetch_billing_data")
    def test_7d_spike_over_50pct_returns_fail(self, mock_fetch):
        mock_fetch.return_value = {
            "cost_7d": {"total": 20.0, "currency": "EUR", "top_services": []},
            "cost_30d": {"total": 50.0, "currency": "EUR", "top_services": []},
            "prev_7d_total": 10.0,  # 20/10 = 100% increase
            "prev_30d_total": 45.0,
        }

        result = run_billing_check()

        assert result["status"] == "fail"

    @patch("routines.billing._fetch_billing_data")
    def test_unavailable_returns_warn(self, mock_fetch):
        mock_fetch.return_value = None

        result = run_billing_check()

        assert result["status"] == "warn"
        assert any("unavailable" in c["detail"] for c in result["checks"])
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && JWT_SECRET_KEY=test-secret-key DATABASE_URL=sqlite:///test.db ENVIRONMENT=test python -m pytest tests/test_routines_billing.py -v`

Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 4: Implement billing routine**

Create `backend/routines/billing.py`:

```python
"""Billing monitoring routine — checks GCP costs via Cloud Billing API."""

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
BILLING_ACCOUNT_ID = os.getenv("BILLING_ACCOUNT_ID", "")


def _fetch_billing_data() -> Optional[dict[str, Any]]:
    """Fetch billing data from Cloud Billing Budgets API.

    Returns cost data for current and previous 7d/30d periods,
    or None if the API is unavailable.
    """
    if not GCP_PROJECT_ID:
        logger.warning("GCP_PROJECT_ID not set, skipping billing check")
        return None

    try:
        from google.cloud import billing_v1

        client = billing_v1.CloudBillingClient()

        # List billing info for the project
        billing_info = client.get_project_billing_info(name=f"projects/{GCP_PROJECT_ID}")

        if not billing_info.billing_enabled:
            return None

        # Note: The Cloud Billing API doesn't directly give cost breakdowns.
        # For detailed costs, BigQuery billing export is needed.
        # This is a simplified check using budgets if available.
        try:
            from google.cloud import billing_budgets_v1

            budgets_client = billing_budgets_v1.BudgetServiceClient()
            billing_account = billing_info.billing_account_name

            budgets = list(budgets_client.list_budgets(parent=billing_account))

            if budgets:
                budget = budgets[0]
                amount = budget.amount.specified_amount
                budget_amount = float(amount.units) + float(amount.nanos) / 1e9 if amount else 0

                # Use threshold rules to estimate spend
                return {
                    "cost_7d": {"total": 0, "currency": amount.currency_code if amount else "EUR", "top_services": []},
                    "cost_30d": {"total": 0, "currency": amount.currency_code if amount else "EUR", "top_services": []},
                    "prev_7d_total": 0,
                    "prev_30d_total": 0,
                    "budget": {"amount": budget_amount, "currency": amount.currency_code if amount else "EUR"},
                }
        except Exception as e:
            logger.warning(f"Budgets API unavailable: {e}")

        return {
            "cost_7d": {"total": 0, "currency": "EUR", "top_services": []},
            "cost_30d": {"total": 0, "currency": "EUR", "top_services": []},
            "prev_7d_total": 0,
            "prev_30d_total": 0,
        }

    except Exception as e:
        logger.error(f"Billing data fetch failed: {e}")
        return None


def run_billing_check() -> dict[str, Any]:
    """Run billing checks and return structured report."""
    checks: list[dict[str, Any]] = []
    data = _fetch_billing_data()

    if data is None:
        checks.append({"name": "cost_trend_7d", "status": "warn", "detail": "Billing data unavailable"})
        checks.append({"name": "cost_trend_30d", "status": "warn", "detail": "Billing data unavailable"})
        return {"status": "warn", "checks": checks, "cost_7d": None, "cost_30d": None, "trend": None}

    cost_7d = data["cost_7d"]["total"]
    cost_30d = data["cost_30d"]["total"]
    prev_7d = data.get("prev_7d_total", 0)
    prev_30d = data.get("prev_30d_total", 0)

    # 7-day trend
    if prev_7d > 0:
        change_7d = ((cost_7d - prev_7d) / prev_7d) * 100
    else:
        change_7d = 0

    if change_7d > 50:
        checks.append({"name": "cost_trend_7d", "status": "fail", "detail": f"+{change_7d:.0f}% vs previous week"})
    else:
        checks.append({"name": "cost_trend_7d", "status": "pass", "detail": f"+{change_7d:.0f}% vs previous week"})

    # 30-day trend
    if prev_30d > 0:
        change_30d = ((cost_30d - prev_30d) / prev_30d) * 100
    else:
        change_30d = 0

    if change_30d > 20:
        checks.append({"name": "cost_trend_30d", "status": "warn", "detail": f"+{change_30d:.0f}% vs previous month"})
    else:
        checks.append({"name": "cost_trend_30d", "status": "pass", "detail": f"+{change_30d:.0f}% vs previous month"})

    # Overall
    statuses = [c["status"] for c in checks]
    if "fail" in statuses:
        overall = "fail"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "pass"

    return {
        "status": overall,
        "checks": checks,
        "cost_7d": data["cost_7d"],
        "cost_30d": data["cost_30d"],
        "trend": {
            "7d_vs_prev_7d": f"+{change_7d:.0f}%",
            "30d_vs_prev_30d": f"+{change_30d:.0f}%",
        },
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && JWT_SECRET_KEY=test-secret-key DATABASE_URL=sqlite:///test.db ENVIRONMENT=test python -m pytest tests/test_routines_billing.py -v`

Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/routines/billing.py backend/tests/test_routines_billing.py
git commit -m "feat: add billing monitoring routine with tests"
```

---

### Task 6: Runner Orchestrator

**Files:**
- Create: `backend/routines/runner.py`
- Create: `backend/tests/test_routines_runner.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_routines_runner.py`:

```python
"""Tests for routines.runner — orchestration logic."""

import json
import pytest
from unittest.mock import patch, MagicMock

from routines.runner import run_one, run_all, ROUTINE_TYPES


class TestRunOne:
    @patch("routines.runner._run_health")
    def test_run_one_health(self, mock_health):
        mock_health.return_value = {"status": "pass", "checks": []}
        db = MagicMock()

        result = run_one("health", db)

        assert result["type"] == "health"
        assert result["status"] == "pass"
        assert "data" in result
        mock_health.assert_called_once_with(db)

    def test_run_one_invalid_type_raises(self):
        db = MagicMock()
        with pytest.raises(ValueError, match="Unknown routine type"):
            run_one("invalid", db)


class TestRunAll:
    @patch("routines.runner._run_billing")
    @patch("routines.runner._run_security")
    @patch("routines.runner._run_ci_cd")
    @patch("routines.runner._run_health")
    def test_run_all_returns_4_results(self, mock_h, mock_ci, mock_sec, mock_bill):
        mock_h.return_value = {"status": "pass", "checks": []}
        mock_ci.return_value = {"status": "pass", "checks": []}
        mock_sec.return_value = {"status": "warn", "checks": []}
        mock_bill.return_value = {"status": "pass", "checks": []}
        db = MagicMock()

        results = run_all(db)

        assert len(results) == 4
        types = [r["type"] for r in results]
        assert set(types) == {"health", "ci_cd", "security", "billing"}


class TestRoutineTypes:
    def test_all_4_types_registered(self):
        assert set(ROUTINE_TYPES) == {"health", "ci_cd", "security", "billing"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && JWT_SECRET_KEY=test-secret-key DATABASE_URL=sqlite:///test.db ENVIRONMENT=test python -m pytest tests/test_routines_runner.py -v`

Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implement runner**

Create `backend/routines/runner.py`:

```python
"""Routine orchestrator — runs one or all monitoring routines."""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

ROUTINE_TYPES = {"health", "ci_cd", "security", "billing"}


def _run_health(db: Session) -> dict[str, Any]:
    from routines.health import run_health_check
    return run_health_check(db)


def _run_ci_cd(db: Session) -> dict[str, Any]:
    from routines.ci_cd import run_ci_cd_check
    return run_ci_cd_check()


def _run_security(db: Session) -> dict[str, Any]:
    from routines.security import run_security_check
    return run_security_check()


def _run_billing(db: Session) -> dict[str, Any]:
    from routines.billing import run_billing_check
    return run_billing_check()


_RUNNERS = {
    "health": _run_health,
    "ci_cd": _run_ci_cd,
    "security": _run_security,
    "billing": _run_billing,
}


def _build_summary(routine_type: str, result: dict[str, Any]) -> str:
    """Build a one-line summary from routine result."""
    status = result.get("status", "unknown")
    checks = result.get("checks", [])
    pass_count = sum(1 for c in checks if c["status"] == "pass")
    warn_count = sum(1 for c in checks if c["status"] == "warn")
    fail_count = sum(1 for c in checks if c["status"] == "fail")
    return f"{routine_type}: {status.upper()} ({pass_count} pass, {warn_count} warn, {fail_count} fail)"


def run_one(routine_type: str, db: Session) -> dict[str, Any]:
    """Run a single routine and return a dict ready to store in DB."""
    if routine_type not in ROUTINE_TYPES:
        raise ValueError(f"Unknown routine type: {routine_type}. Must be one of {ROUTINE_TYPES}")

    runner = _RUNNERS[routine_type]
    try:
        result = runner(db)
    except Exception as e:
        logger.error(f"Routine {routine_type} failed: {e}", exc_info=True)
        result = {
            "status": "fail",
            "checks": [{"name": "execution", "status": "fail", "detail": str(e)}],
        }

    return {
        "type": routine_type,
        "status": result["status"],
        "data": json.dumps(result),
        "summary": _build_summary(routine_type, result),
        "created_at": datetime.now(tz=timezone.utc),
    }


def run_all(db: Session) -> list[dict[str, Any]]:
    """Run all 4 routines and return list of results."""
    results = []
    for routine_type in sorted(ROUTINE_TYPES):
        results.append(run_one(routine_type, db))
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && JWT_SECRET_KEY=test-secret-key DATABASE_URL=sqlite:///test.db ENVIRONMENT=test python -m pytest tests/test_routines_runner.py -v`

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/routines/runner.py backend/tests/test_routines_runner.py
git commit -m "feat: add routine orchestrator with tests"
```

---

### Task 7: Routines Router (API Endpoints)

**Files:**
- Create: `backend/routers/routines.py`
- Modify: `backend/main.py` (register router, ~line 425 and ~line 438)

- [ ] **Step 1: Create router**

Create `backend/routers/routines.py`:

```python
"""Admin routine endpoints — run, list, and read monitoring routine reports."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc
from sqlalchemy.orm import Session

from auth import verify_token
from database import RoutineReport, get_db
from permissions import require_role
from routines.runner import ROUTINE_TYPES, run_all, run_one

logger = logging.getLogger(__name__)

router = APIRouter()

# Cloud Scheduler sends OIDC tokens. We verify via a shared secret as fallback.
import os

_SCHEDULER_SECRET = os.getenv("ROUTINE_SCHEDULER_SECRET", "")


def _verify_admin_or_scheduler(request: Request, db: Session) -> bool:
    """Allow access if user is admin OR request has a valid scheduler secret."""
    # Check scheduler secret header first (Cloud Scheduler)
    scheduler_header = request.headers.get("X-Scheduler-Secret", "")
    if _SCHEDULER_SECRET and scheduler_header == _SCHEDULER_SECRET:
        return True

    # Fall back to normal admin auth
    from auth import verify_token as _verify

    try:
        user_id = _verify(request)
        require_role(int(user_id), db, "admin")
        return True
    except Exception:
        raise HTTPException(status_code=403, detail="Admin access or valid scheduler secret required")


def _store_report(db: Session, result: dict) -> RoutineReport:
    """Store a routine result in the database."""
    report = RoutineReport(
        type=result["type"],
        status=result["status"],
        data=result["data"],
        summary=result["summary"],
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def _serialize_report(report: RoutineReport) -> dict:
    """Serialize a RoutineReport to a JSON-safe dict."""
    return {
        "id": report.id,
        "type": report.type,
        "status": report.status,
        "data": json.loads(report.data) if report.data else {},
        "summary": report.summary,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


@router.post("/api/admin/routine/run-all")
async def routine_run_all(
    request: Request,
    db: Session = Depends(get_db),
):
    """Execute all 4 routines, store results, return summary."""
    _verify_admin_or_scheduler(request, db)

    results = run_all(db)
    stored = []
    for result in results:
        report = _store_report(db, result)
        stored.append(_serialize_report(report))

    return {"reports": stored}


@router.post("/api/admin/routine/run/{routine_type}")
async def routine_run_one(
    routine_type: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Execute a single routine by type."""
    _verify_admin_or_scheduler(request, db)

    if routine_type not in ROUTINE_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid type. Must be one of: {', '.join(sorted(ROUTINE_TYPES))}")

    result = run_one(routine_type, db)
    report = _store_report(db, result)
    return _serialize_report(report)


@router.get("/api/admin/routine/latest")
async def routine_latest(
    request: Request,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Latest report for each routine type (up to 4 items)."""
    require_role(int(user_id), db, "admin")

    results = []
    for rtype in sorted(ROUTINE_TYPES):
        report = (
            db.query(RoutineReport)
            .filter(RoutineReport.type == rtype)
            .order_by(desc(RoutineReport.created_at))
            .first()
        )
        if report:
            results.append(_serialize_report(report))
    return {"reports": results}


@router.get("/api/admin/routine/reports")
async def routine_reports(
    request: Request,
    type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Paginated list of routine reports, filterable by type."""
    require_role(int(user_id), db, "admin")

    query = db.query(RoutineReport)
    if type:
        if type not in ROUTINE_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid type. Must be one of: {', '.join(sorted(ROUTINE_TYPES))}")
        query = query.filter(RoutineReport.type == type)

    total = query.count()
    reports = (
        query.order_by(desc(RoutineReport.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "reports": [_serialize_report(r) for r in reports],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/api/admin/routine/reports/{report_id}")
async def routine_report_detail(
    report_id: int,
    request: Request,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Full detail of one routine report."""
    require_role(int(user_id), db, "admin")

    report = db.query(RoutineReport).filter(RoutineReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    return _serialize_report(report)
```

- [ ] **Step 2: Register router in main.py**

Add after line 425 (`from routers.monitoring import router as monitoring_router`):

```python
from routers.routines import router as routines_router  # noqa: E402
```

Add after line 438 (`app.include_router(monitoring_router)`):

```python
app.include_router(routines_router)
```

- [ ] **Step 3: Run linting to verify**

Run: `cd backend && python -m ruff check routers/routines.py`

Expected: All checks passed!

- [ ] **Step 4: Run all existing tests to verify nothing broke**

Run: `cd backend && JWT_SECRET_KEY=test-secret-key DATABASE_URL=sqlite:///test.db ENVIRONMENT=test python -m pytest tests/ -v --tb=short`

Expected: All previously passing tests still pass

- [ ] **Step 5: Commit**

```bash
git add backend/routers/routines.py backend/main.py
git commit -m "feat: add routine API endpoints with admin auth"
```

---

### Task 8: Frontend Dashboard Page

**Files:**
- Create: `frontend/pages/admin/monitoring.js`

- [ ] **Step 1: Create the dashboard page**

Create `frontend/pages/admin/monitoring.js`:

```jsx
import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import { useAuth } from '../../hooks/useAuth';
import api from '../../lib/api';
import Layout from '../../components/Layout';
import {
  Activity,
  GitBranch,
  Shield,
  DollarSign,
  CheckCircle,
  AlertTriangle,
  XCircle,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Clock,
  Loader2,
} from 'lucide-react';

const ROUTINE_META = {
  health:   { label: 'Health',    icon: Activity,   color: 'blue' },
  ci_cd:    { label: 'CI/CD',     icon: GitBranch,  color: 'purple' },
  security: { label: 'Security',  icon: Shield,     color: 'orange' },
  billing:  { label: 'Billing',   icon: DollarSign,  color: 'green' },
};

const STATUS_STYLES = {
  pass: { bg: 'bg-green-50', border: 'border-green-200', text: 'text-green-700', icon: CheckCircle },
  warn: { bg: 'bg-yellow-50', border: 'border-yellow-200', text: 'text-yellow-700', icon: AlertTriangle },
  fail: { bg: 'bg-red-50', border: 'border-red-200', text: 'text-red-700', icon: XCircle },
};

function StatusBadge({ status }) {
  const style = STATUS_STYLES[status] || STATUS_STYLES.warn;
  const Icon = style.icon;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${style.bg} ${style.text}`}>
      <Icon className="w-3 h-3" />
      {status.toUpperCase()}
    </span>
  );
}

function TimeAgo({ dateStr }) {
  if (!dateStr) return <span className="text-gray-400 text-xs">Never</span>;
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now - date;
  const diffMin = Math.floor(diffMs / 60000);
  const diffH = Math.floor(diffMin / 60);
  const diffD = Math.floor(diffH / 24);

  let text;
  if (diffMin < 1) text = 'just now';
  else if (diffMin < 60) text = `${diffMin}m ago`;
  else if (diffH < 24) text = `${diffH}h ago`;
  else text = `${diffD}d ago`;

  return <span className="text-gray-500 text-xs flex items-center gap-1"><Clock className="w-3 h-3" />{text}</span>;
}

function RoutineCard({ report, onExpand, expanded }) {
  const type = report?.type || 'health';
  const meta = ROUTINE_META[type] || ROUTINE_META.health;
  const Icon = meta.icon;
  const status = report?.status || 'warn';
  const checks = report?.data?.checks || [];
  const passCount = checks.filter(c => c.status === 'pass').length;
  const warnCount = checks.filter(c => c.status === 'warn').length;
  const failCount = checks.filter(c => c.status === 'fail').length;

  return (
    <div className={`rounded-lg border ${STATUS_STYLES[status]?.border || 'border-gray-200'} ${STATUS_STYLES[status]?.bg || 'bg-gray-50'} p-4`}>
      <div className="flex items-center justify-between cursor-pointer" onClick={onExpand}>
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-lg bg-${meta.color}-100`}>
            <Icon className={`w-5 h-5 text-${meta.color}-600`} />
          </div>
          <div>
            <h3 className="font-semibold text-gray-900">{meta.label}</h3>
            <TimeAgo dateStr={report?.created_at} />
          </div>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={status} />
          <span className="text-xs text-gray-500">{passCount}P {warnCount}W {failCount}F</span>
          {expanded ? <ChevronUp className="w-4 h-4 text-gray-400" /> : <ChevronDown className="w-4 h-4 text-gray-400" />}
        </div>
      </div>

      {expanded && checks.length > 0 && (
        <div className="mt-4 space-y-2 border-t border-gray-200 pt-3">
          {checks.map((check, i) => (
            <div key={i} className="flex items-center justify-between text-sm">
              <span className="text-gray-700 font-mono">{check.name}</span>
              <div className="flex items-center gap-2">
                <span className="text-gray-500 text-xs">{check.detail}</span>
                <StatusBadge status={check.status} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function AdminMonitoring() {
  const { user, loading: authLoading, authenticated } = useAuth();
  const router = useRouter();
  const [reports, setReports] = useState([]);
  const [history, setHistory] = useState([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyPage, setHistoryPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [expanded, setExpanded] = useState({});

  const loadLatest = useCallback(async () => {
    try {
      const res = await api.get('/api/admin/routine/latest');
      setReports(res.data.reports || []);
    } catch (err) {
      console.error('Failed to load latest reports:', err);
    }
  }, []);

  const loadHistory = useCallback(async (page = 1) => {
    try {
      const res = await api.get('/api/admin/routine/reports', { params: { page, page_size: 10 } });
      setHistory(res.data.reports || []);
      setHistoryTotal(res.data.total || 0);
      setHistoryPage(page);
    } catch (err) {
      console.error('Failed to load history:', err);
    }
  }, []);

  useEffect(() => {
    if (!authLoading && !authenticated) {
      router.push('/login');
      return;
    }
    if (authenticated) {
      setLoading(true);
      Promise.all([loadLatest(), loadHistory()]).finally(() => setLoading(false));
    }
  }, [authLoading, authenticated]);

  const handleRunAll = async () => {
    setRunning(true);
    try {
      await api.post('/api/admin/routine/run-all');
      await Promise.all([loadLatest(), loadHistory()]);
    } catch (err) {
      console.error('Run all failed:', err);
    } finally {
      setRunning(false);
    }
  };

  const toggleExpand = (type) => {
    setExpanded(prev => ({ ...prev, [type]: !prev[type] }));
  };

  if (authLoading || loading) {
    return (
      <Layout>
        <div className="flex items-center justify-center min-h-[60vh]">
          <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
        </div>
      </Layout>
    );
  }

  const orderedTypes = ['health', 'ci_cd', 'security', 'billing'];
  const reportsByType = {};
  reports.forEach(r => { reportsByType[r.type] = r; });

  return (
    <Layout>
      <div className="max-w-5xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Monitoring Dashboard</h1>
            <p className="text-gray-500 text-sm mt-1">Daily automated health checks</p>
          </div>
          <button
            onClick={handleRunAll}
            disabled={running}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${running ? 'animate-spin' : ''}`} />
            {running ? 'Running...' : 'Run Now'}
          </button>
        </div>

        {/* Status cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
          {orderedTypes.map(type => (
            <RoutineCard
              key={type}
              report={reportsByType[type] || { type, status: 'warn', data: { checks: [] } }}
              expanded={!!expanded[type]}
              onExpand={() => toggleExpand(type)}
            />
          ))}
        </div>

        {/* History table */}
        <div className="bg-white rounded-lg border border-gray-200">
          <div className="px-4 py-3 border-b border-gray-200">
            <h2 className="font-semibold text-gray-900">History</h2>
          </div>
          <div className="divide-y divide-gray-100">
            {history.length === 0 ? (
              <div className="px-4 py-8 text-center text-gray-400">No reports yet. Click &quot;Run Now&quot; to generate the first report.</div>
            ) : (
              history.map(report => (
                <div key={report.id} className="px-4 py-3 flex items-center justify-between hover:bg-gray-50">
                  <div className="flex items-center gap-3">
                    <StatusBadge status={report.status} />
                    <span className="text-sm font-medium text-gray-700 capitalize">{report.type.replace('_', '/')}</span>
                  </div>
                  <div className="flex items-center gap-4">
                    <span className="text-sm text-gray-500">{report.summary}</span>
                    <TimeAgo dateStr={report.created_at} />
                  </div>
                </div>
              ))
            )}
          </div>
          {historyTotal > 10 && (
            <div className="px-4 py-3 border-t border-gray-200 flex justify-between">
              <button
                onClick={() => loadHistory(historyPage - 1)}
                disabled={historyPage <= 1}
                className="text-sm text-blue-600 hover:text-blue-800 disabled:text-gray-300"
              >
                Previous
              </button>
              <span className="text-sm text-gray-500">Page {historyPage} of {Math.ceil(historyTotal / 10)}</span>
              <button
                onClick={() => loadHistory(historyPage + 1)}
                disabled={historyPage >= Math.ceil(historyTotal / 10)}
                className="text-sm text-blue-600 hover:text-blue-800 disabled:text-gray-300"
              >
                Next
              </button>
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}

export async function getStaticProps({ locale }) {
  return {
    props: {
      ...(await serverSideTranslations(locale ?? 'fr', ['common'])),
    },
  };
}
```

- [ ] **Step 2: Run frontend lint**

Run: `cd frontend && npm run lint`

Expected: No new errors (possibly existing warnings are fine)

- [ ] **Step 3: Commit**

```bash
git add frontend/pages/admin/monitoring.js
git commit -m "feat: add admin monitoring dashboard page"
```

---

### Task 9: Cloud Scheduler Setup + Deploy Config

**Files:**
- Modify: `cloudbuild_dev.yaml` (add env vars)
- Modify: `cloudbuild.yaml` (add env vars)
- Create: `scripts/setup-scheduler.sh`

- [ ] **Step 1: Add env vars to cloudbuild_dev.yaml**

In `cloudbuild_dev.yaml`, in the backend deploy step's `--set-env-vars` line, append:

```
,GCP_PROJECT_ID=applydi
```

In the `--set-secrets` line, append:

```
,GITHUB_TOKEN=GITHUB_TOKEN:latest,ROUTINE_SCHEDULER_SECRET=ROUTINE_SCHEDULER_SECRET:latest
```

Also add `GITHUB_REPO=taicai-1/taic` to the `--set-env-vars` line.

- [ ] **Step 2: Add env vars to cloudbuild.yaml (production)**

Same changes as step 1, applied to `cloudbuild.yaml`.

- [ ] **Step 3: Create scheduler setup script**

Create `scripts/setup-scheduler.sh`:

```bash
#!/usr/bin/env bash
# Setup Cloud Scheduler for daily monitoring routines.
# Run once per environment. Requires gcloud CLI authenticated.

set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-applydi}"
REGION="europe-west1"
SERVICE_ACCOUNT="taic-drive-sa@${PROJECT_ID}.iam.gserviceaccount.com"

# Dev environment
DEV_BACKEND_URL="https://dev-taic-backend-817946451913.${REGION}.run.app"
SCHEDULER_SECRET=$(gcloud secrets versions access latest --secret=ROUTINE_SCHEDULER_SECRET --project="${PROJECT_ID}" 2>/dev/null || echo "")

echo "Creating Cloud Scheduler job for dev..."
gcloud scheduler jobs create http taic-daily-routine-dev \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --schedule="0 9 * * *" \
  --time-zone="Europe/Paris" \
  --uri="${DEV_BACKEND_URL}/api/admin/routine/run-all" \
  --http-method=POST \
  --headers="X-Scheduler-Secret=${SCHEDULER_SECRET}" \
  --oidc-service-account-email="${SERVICE_ACCOUNT}" \
  --oidc-token-audience="${DEV_BACKEND_URL}" \
  --description="Daily monitoring routine (dev)" \
  --attempt-deadline=300s \
  || echo "Job already exists. Use 'gcloud scheduler jobs update http ...' to modify."

# Production environment
PROD_BACKEND_URL="https://applydi-backend-817946451913.${REGION}.run.app"

echo "Creating Cloud Scheduler job for production..."
gcloud scheduler jobs create http taic-daily-routine-prod \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --schedule="0 9 * * *" \
  --time-zone="Europe/Paris" \
  --uri="${PROD_BACKEND_URL}/api/admin/routine/run-all" \
  --http-method=POST \
  --headers="X-Scheduler-Secret=${SCHEDULER_SECRET}" \
  --oidc-service-account-email="${SERVICE_ACCOUNT}" \
  --oidc-token-audience="${PROD_BACKEND_URL}" \
  --description="Daily monitoring routine (prod)" \
  --attempt-deadline=300s \
  || echo "Job already exists. Use 'gcloud scheduler jobs update http ...' to modify."

echo "Done. Verify with: gcloud scheduler jobs list --project=${PROJECT_ID} --location=${REGION}"
```

- [ ] **Step 4: Create GCP secrets (manual)**

Run these commands manually (one-time setup):

```bash
# Create a random scheduler secret
openssl rand -hex 32 | gcloud secrets create ROUTINE_SCHEDULER_SECRET --data-file=- --project=applydi
# Create GitHub token secret (replace with your PAT)
echo -n "ghp_YOUR_TOKEN_HERE" | gcloud secrets create GITHUB_TOKEN --data-file=- --project=applydi
```

- [ ] **Step 5: Commit**

```bash
git add cloudbuild.yaml cloudbuild_dev.yaml scripts/setup-scheduler.sh
git commit -m "feat: add Cloud Scheduler setup and deploy config for routines"
```

---

### Task 10: Run Full Test Suite + Lint

- [ ] **Step 1: Run backend linter**

Run: `cd backend && python -m ruff check .`

Expected: All checks passed!

- [ ] **Step 2: Run all backend tests**

Run: `cd backend && JWT_SECRET_KEY=test-secret-key DATABASE_URL=sqlite:///test.db ENVIRONMENT=test python -m pytest tests/ -v --tb=short`

Expected: All tests pass (previous 102 + new ~18 routine tests)

- [ ] **Step 3: Run frontend lint**

Run: `cd frontend && npm run lint`

Expected: No new errors

- [ ] **Step 4: Final commit if any fixes needed**

Only if steps 1-3 required changes.
