# Manual Org Creation Approval — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate organization (Company) creation behind manual admin approval via magic-link emails sent to `jeremy@taic.co`.

**Architecture:** New `CompanyCreationRequest` DB table stores pending demands. New endpoints replace direct `POST /api/companies`. Admin receives email with approve/reject magic links pointing to HTML confirmation pages served by FastAPI. On approval, the existing `Company` + `CompanyMembership` creation logic runs and the user is notified by email.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, Redis (rate-limit cache), SMTP (Google Workspace), Next.js, Tailwind CSS, i18next.

**Spec:** `docs/superpowers/specs/2026-04-16-org-creation-manual-approval-design.md`

---

## File Structure

**Backend files to create:**
- `backend/migrations/004_company_creation_requests.sql` — DDL for new table
- `backend/admin_html_pages.py` — FastAPI HTMLResponse renderers for admin confirmation pages (small, focused module)

**Backend files to modify:**
- `backend/database.py` — add `CompanyCreationRequest` SQLAlchemy model
- `backend/validation.py` — add `CompanyRequestCreateValidated` Pydantic schema
- `backend/email_service.py` — add 3 email-rendering functions (admin notif, user approved, user rejected)
- `backend/main.py` — add 4 endpoints, IP rate-limit helper, remove old `POST /api/companies`, normalize error messages to "organisation"
- `backend/.env.example` — add `ADMIN_NOTIFICATION_EMAIL`
- `backend/tests/test_validation.py` — add tests for new Pydantic schema

**Backend files to create for tests:**
- `backend/tests/test_company_request.py` — unit tests for token generation, email rendering, helpers

**Frontend files to modify:**
- `frontend/pages/organization.js` — switch to `/api/companies/request`, add pending/rejected UI states
- `frontend/public/locales/fr/organization.json` — add new i18n keys
- `frontend/public/locales/en/organization.json` — add new i18n keys
- `frontend/hooks/useAuth.js` — (no changes needed; `user.company_id` already exposed)

---

## Task 1: Create migration SQL file

**Files:**
- Create: `backend/migrations/004_company_creation_requests.sql`

- [ ] **Step 1: Write the migration SQL**

Create `backend/migrations/004_company_creation_requests.sql`:

```sql
-- ============================================================================
-- Migration 004 - Add company_creation_requests table
-- ============================================================================
--
-- Stores user requests to create a new organization, pending manual approval
-- by an administrator (default: jeremy@taic.co). Linked to companies when
-- approved via company_id (nullable until decision).
--
-- This migration is idempotent: safe to re-run.
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS company_creation_requests (
    id               SERIAL PRIMARY KEY,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    requested_name   VARCHAR(200) NOT NULL,
    status           VARCHAR(20) NOT NULL DEFAULT 'pending',
    token            VARCHAR(128) NOT NULL UNIQUE,
    created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    decided_at       TIMESTAMP,
    decided_reason   TEXT,
    company_id       INTEGER REFERENCES companies(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_ccr_user_id ON company_creation_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_ccr_token ON company_creation_requests(token);
CREATE INDEX IF NOT EXISTS idx_ccr_status ON company_creation_requests(status);

COMMIT;

-- ============================================================================
-- VERIFICATION:
--   SELECT column_name, data_type, is_nullable
--   FROM information_schema.columns
--   WHERE table_name = 'company_creation_requests';
-- ============================================================================
```

- [ ] **Step 2: Apply migration locally and verify**

With a local PostgreSQL (via `docker-compose up db`) running:

```bash
psql -h localhost -U taic -d taic -f backend/migrations/004_company_creation_requests.sql
```

Then verify:

```bash
psql -h localhost -U taic -d taic -c "\d company_creation_requests"
```

Expected: table listed with all 9 columns, indexes on user_id/token/status, and foreign keys to users(id) and companies(id).

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/004_company_creation_requests.sql
git commit -m "feat(db): add migration for company_creation_requests table"
```

---

## Task 2: Add `CompanyCreationRequest` SQLAlchemy model

**Files:**
- Modify: `backend/database.py` (add model after `CompanyInvitation` class, around line 233)

- [ ] **Step 1: Add the model**

In `backend/database.py`, after the `CompanyInvitation` class (before `class Agent`), add:

```python
class CompanyCreationRequest(Base):
    __tablename__ = "company_creation_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_name = Column(String(200), nullable=False)
    status = Column(String(20), nullable=False, default="pending")  # 'pending' | 'approved' | 'rejected'
    token = Column(String(128), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)
    decided_reason = Column(Text, nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)

    user = relationship("User", foreign_keys=[user_id])
    company = relationship("Company", foreign_keys=[company_id])
```

- [ ] **Step 2: Verify no typos via a Python syntax check**

Run: `python -c "import ast; ast.parse(open('backend/database.py').read())"`
Expected: no output (success) or SyntaxError if broken.

- [ ] **Step 3: Commit**

```bash
git add backend/database.py
git commit -m "feat(db): add CompanyCreationRequest model"
```

---

## Task 3: Add Pydantic validation schema

**Files:**
- Modify: `backend/validation.py` (add after `TeamCreateValidated` around line 425)
- Test: `backend/tests/test_validation.py` (append class at end)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_validation.py`:

```python
class TestCompanyRequestCreateValidated:
    def test_accepts_valid_name(self):
        from validation import CompanyRequestCreateValidated
        v = CompanyRequestCreateValidated(name="Ma Boîte")
        assert v.name == "Ma Boîte"

    def test_rejects_empty_name(self):
        from validation import CompanyRequestCreateValidated
        with pytest.raises(ValidationError):
            CompanyRequestCreateValidated(name="")

    def test_rejects_name_too_long(self):
        from validation import CompanyRequestCreateValidated
        with pytest.raises(ValidationError):
            CompanyRequestCreateValidated(name="a" * 201)

    def test_strips_and_sanitizes(self):
        from validation import CompanyRequestCreateValidated
        v = CompanyRequestCreateValidated(name="  <script>alert('x')</script>Test  ")
        assert "<script>" not in v.name
        assert "Test" in v.name

    def test_rejects_name_too_short(self):
        from validation import CompanyRequestCreateValidated
        with pytest.raises(ValidationError):
            CompanyRequestCreateValidated(name="a")  # min_length=2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_validation.py::TestCompanyRequestCreateValidated -v`
Expected: FAIL with `ImportError: cannot import name 'CompanyRequestCreateValidated'`

- [ ] **Step 3: Add the schema**

In `backend/validation.py`, locate the `TeamCreateValidated` class and add after it:

```python
class CompanyRequestCreateValidated(BaseModel):
    """Company creation request with validation"""

    name: str = Field(..., min_length=2, max_length=200)

    @validator("name")
    def validate_name(cls, v):
        v = sanitize_text(v, 200)
        if not v or len(v) < 2:
            raise ValueError("Organization name must be at least 2 characters")
        return v
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_validation.py::TestCompanyRequestCreateValidated -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/validation.py backend/tests/test_validation.py
git commit -m "feat(validation): add CompanyRequestCreateValidated schema"
```

---

## Task 4: Add email rendering functions

**Files:**
- Modify: `backend/email_service.py` (append new functions at end of file)
- Test: `backend/tests/test_company_request.py` (create new test file)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_company_request.py`:

```python
"""Unit tests for company creation request helpers."""

import pytest


class TestEmailRendering:
    def test_admin_notification_renders(self):
        from email_service import render_admin_org_request_email
        html = render_admin_org_request_email(
            requester_email="alice@example.com",
            requested_name="Ma Boîte",
            approve_url="https://api.taic.co/api/admin/companies/request/abc?action=approve",
            reject_url="https://api.taic.co/api/admin/companies/request/abc?action=reject",
        )
        assert "alice@example.com" in html
        assert "Ma Boîte" in html
        assert "Approuver" in html
        assert "Refuser" in html
        assert "https://api.taic.co/api/admin/companies/request/abc?action=approve" in html

    def test_user_approved_renders(self):
        from email_service import render_user_org_approved_email
        html = render_user_org_approved_email(
            requested_name="Ma Boîte",
            app_url="https://app.taic.co/organization",
        )
        assert "Ma Boîte" in html
        assert "approuvée" in html.lower()
        assert "https://app.taic.co/organization" in html

    def test_user_rejected_renders_with_reason(self):
        from email_service import render_user_org_rejected_email
        html = render_user_org_rejected_email(
            requested_name="Ma Boîte",
            reason="Nom non conforme",
            app_url="https://app.taic.co/organization",
        )
        assert "Ma Boîte" in html
        assert "Nom non conforme" in html

    def test_user_rejected_renders_without_reason(self):
        from email_service import render_user_org_rejected_email
        html = render_user_org_rejected_email(
            requested_name="Ma Boîte",
            reason=None,
            app_url="https://app.taic.co/organization",
        )
        assert "Ma Boîte" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_company_request.py::TestEmailRendering -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Add the rendering functions**

Append to `backend/email_service.py`:

```python
def render_admin_org_request_email(
    requester_email: str,
    requested_name: str,
    approve_url: str,
    reject_url: str,
) -> str:
    """Render the HTML email sent to admin when a new org creation is requested."""
    content = f"""
        <h2 style="color:#111827; font-size:20px; margin:0 0 16px; font-weight:700;">
            Nouvelle demande d'organisation
        </h2>
        <p style="color:#374151; font-size:15px; line-height:1.5; margin:0 0 8px;">
            <strong>{requester_email}</strong> souhaite créer l'organisation&nbsp;:
        </p>
        <p style="color:#111827; font-size:18px; font-weight:600; margin:0 0 24px; padding:12px 16px; background:#f3f4f6; border-radius:8px;">
            {requested_name}
        </p>
        <p style="color:#374151; font-size:14px; line-height:1.5; margin:0 0 24px;">
            Choisissez une action&nbsp;:
        </p>
        <table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 auto;">
            <tr>
                <td style="padding:0 8px;">
                    <a href="{approve_url}"
                       style="display:inline-block; padding:14px 28px; background:#10b981; color:#ffffff;
                              text-decoration:none; border-radius:8px; font-weight:600; font-size:15px;">
                        ✅ Approuver
                    </a>
                </td>
                <td style="padding:0 8px;">
                    <a href="{reject_url}"
                       style="display:inline-block; padding:14px 28px; background:#ef4444; color:#ffffff;
                              text-decoration:none; border-radius:8px; font-weight:600; font-size:15px;">
                        ❌ Refuser
                    </a>
                </td>
            </tr>
        </table>
        <p style="color:#9ca3af; font-size:12px; line-height:1.5; margin:24px 0 0; text-align:center;">
            Les liens pointent vers une page de confirmation — rien n'est exécuté automatiquement.
        </p>
    """
    return _wrap_template(
        content,
        preheader=f"{requester_email} demande '{requested_name}'",
    )


def render_user_org_approved_email(requested_name: str, app_url: str) -> str:
    """Render the HTML email sent to user when their org request is approved."""
    content = f"""
        <h2 style="color:#111827; font-size:20px; margin:0 0 16px; font-weight:700;">
            🎉 Votre organisation a été approuvée
        </h2>
        <p style="color:#374151; font-size:15px; line-height:1.5; margin:0 0 16px;">
            Bonne nouvelle&nbsp;: votre organisation
            <strong>{requested_name}</strong> a été approuvée et est maintenant active.
        </p>
        <p style="color:#374151; font-size:15px; line-height:1.5; margin:0 0 24px;">
            Vous pouvez dès à présent inviter vos collaborateurs et configurer vos intégrations.
        </p>
        <div style="text-align:center; margin:32px 0;">
            <a href="{app_url}"
               style="display:inline-block; padding:14px 32px; background:linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
                      color:#ffffff; text-decoration:none; border-radius:8px; font-weight:600; font-size:15px;">
                Accéder à mon organisation
            </a>
        </div>
    """
    return _wrap_template(content, preheader=f"'{requested_name}' est prête")


def render_user_org_rejected_email(requested_name: str, reason: str | None, app_url: str) -> str:
    """Render the HTML email sent to user when their org request is rejected."""
    reason_block = ""
    if reason:
        reason_block = f"""
        <p style="color:#374151; font-size:14px; line-height:1.5; margin:0 0 16px; padding:12px 16px; background:#fef2f2; border-left:3px solid #ef4444; border-radius:4px;">
            <strong>Raison&nbsp;:</strong> {reason}
        </p>
        """
    content = f"""
        <h2 style="color:#111827; font-size:20px; margin:0 0 16px; font-weight:700;">
            Votre demande d'organisation
        </h2>
        <p style="color:#374151; font-size:15px; line-height:1.5; margin:0 0 16px;">
            Votre demande pour l'organisation <strong>{requested_name}</strong>
            n'a pas pu être acceptée pour le moment.
        </p>
        {reason_block}
        <p style="color:#374151; font-size:15px; line-height:1.5; margin:0 0 24px;">
            Vous pouvez soumettre une nouvelle demande depuis votre espace.
        </p>
        <div style="text-align:center; margin:32px 0;">
            <a href="{app_url}"
               style="display:inline-block; padding:14px 32px; background:#6366f1;
                      color:#ffffff; text-decoration:none; border-radius:8px; font-weight:600; font-size:15px;">
                Soumettre une nouvelle demande
            </a>
        </div>
    """
    return _wrap_template(content, preheader="Information sur votre demande")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_company_request.py::TestEmailRendering -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/email_service.py backend/tests/test_company_request.py
git commit -m "feat(email): add org creation request email templates"
```

---

## Task 5: Create admin HTML confirmation page module

**Files:**
- Create: `backend/admin_html_pages.py`

- [ ] **Step 1: Create the module**

Create `backend/admin_html_pages.py`:

```python
"""HTML pages served to the admin for org creation request confirmation.

These pages are minimal, brandless-but-clean HTML rendered by FastAPI HTMLResponse.
They exist separately from the Next.js app because they are hit directly from
email links (not through the standard auth flow).
"""

from html import escape


def _base_page(title: str, body_html: str) -> str:
    """Wrap content in a minimal full-page HTML document."""
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escape(title)} — TAIC Companion</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f3f4f6; margin: 0; padding: 24px;
            min-height: 100vh; display: flex; align-items: center; justify-content: center;
        }}
        .card {{
            background: #fff; max-width: 480px; width: 100%;
            padding: 40px 32px; border-radius: 16px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.07);
            text-align: center;
        }}
        .header {{
            background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
            color: #fff; padding: 20px; border-radius: 12px 12px 0 0;
            margin: -40px -32px 32px; font-size: 18px; font-weight: 700;
        }}
        h1 {{ color: #111827; font-size: 22px; margin: 0 0 16px; }}
        p {{ color: #374151; font-size: 15px; line-height: 1.5; margin: 0 0 16px; }}
        .org-name {{
            display: inline-block; padding: 12px 16px; background: #f3f4f6;
            border-radius: 8px; font-weight: 600; color: #111827; margin: 8px 0;
        }}
        button, .btn {{
            display: inline-block; padding: 14px 28px; font-weight: 600;
            font-size: 15px; border-radius: 8px; border: none; cursor: pointer;
            text-decoration: none;
        }}
        .btn-approve {{ background: #10b981; color: #fff; }}
        .btn-reject {{ background: #ef4444; color: #fff; }}
        .btn-secondary {{ background: #e5e7eb; color: #374151; margin-right: 8px; }}
        .success {{ color: #10b981; }}
        .error {{ color: #ef4444; }}
        textarea {{
            width: 100%; padding: 12px; border: 1px solid #e5e7eb;
            border-radius: 8px; font-family: inherit; font-size: 14px;
            margin: 12px 0; resize: vertical; min-height: 80px;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="header">TAIC Companion — Admin</div>
        {body_html}
    </div>
</body>
</html>"""


def confirm_approve_page(token: str, requester_email: str, requested_name: str, post_url: str) -> str:
    """Page asking admin to confirm the approval of an org creation request."""
    body = f"""
        <h1>Approuver cette organisation ?</h1>
        <p>Demandeur&nbsp;: <strong>{escape(requester_email)}</strong></p>
        <p>Organisation&nbsp;:</p>
        <div class="org-name">{escape(requested_name)}</div>
        <form method="POST" action="{escape(post_url)}">
            <input type="hidden" name="action" value="approve">
            <p style="margin-top: 24px;">
                <a href="/" class="btn btn-secondary">Annuler</a>
                <button type="submit" class="btn btn-approve">✅ Confirmer l'approbation</button>
            </p>
        </form>
    """
    return _base_page("Approuver", body)


def confirm_reject_page(token: str, requester_email: str, requested_name: str, post_url: str) -> str:
    """Page asking admin to confirm the rejection, with optional reason."""
    body = f"""
        <h1>Refuser cette demande ?</h1>
        <p>Demandeur&nbsp;: <strong>{escape(requester_email)}</strong></p>
        <p>Organisation demandée&nbsp;:</p>
        <div class="org-name">{escape(requested_name)}</div>
        <form method="POST" action="{escape(post_url)}">
            <input type="hidden" name="action" value="reject">
            <label style="display:block; text-align:left; margin-top:24px; font-size:14px; color:#374151; font-weight:600;">
                Raison (optionnelle)
            </label>
            <textarea name="reason" placeholder="Ex: Nom non conforme..."></textarea>
            <p>
                <a href="/" class="btn btn-secondary">Annuler</a>
                <button type="submit" class="btn btn-reject">❌ Confirmer le refus</button>
            </p>
        </form>
    """
    return _base_page("Refuser", body)


def success_page(message: str) -> str:
    body = f"""
        <h1 class="success">✅ Action effectuée</h1>
        <p>{escape(message)}</p>
    """
    return _base_page("Succès", body)


def error_page(message: str) -> str:
    body = f"""
        <h1 class="error">❌ Erreur</h1>
        <p>{escape(message)}</p>
    """
    return _base_page("Erreur", body)
```

- [ ] **Step 2: Verify Python syntax**

Run: `python -c "import ast; ast.parse(open('backend/admin_html_pages.py').read())"`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add backend/admin_html_pages.py
git commit -m "feat(admin): add HTML confirmation page templates for org requests"
```

---

## Task 6: Add IP rate-limit helper

**Files:**
- Modify: `backend/main.py` (add constants and helper near the existing rate limit code, around line 265)
- Test: `backend/tests/test_company_request.py` (append test class)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_company_request.py`:

```python
class TestIpRateLimit:
    """In-memory fallback behavior (Redis path tested manually in staging)."""

    def test_allows_first_five_requests(self):
        # Import fresh to reset module state between tests
        import importlib
        import main
        importlib.reload(main)  # ensure _org_request_rate_limit_fallback is clean

        ip = "10.0.0.1"
        for _ in range(5):
            assert main._check_org_request_rate_limit(ip) is True

    def test_blocks_sixth_request_within_window(self):
        import importlib
        import main
        importlib.reload(main)

        ip = "10.0.0.2"
        for _ in range(5):
            main._check_org_request_rate_limit(ip)
        assert main._check_org_request_rate_limit(ip) is False

    def test_different_ips_isolated(self):
        import importlib
        import main
        importlib.reload(main)

        for _ in range(5):
            main._check_org_request_rate_limit("10.0.0.3")
        assert main._check_org_request_rate_limit("10.0.0.4") is True
```

Note: `main.py` imports fail in unit tests because of DB pool config (the `test_health` in the existing test suite is skipped for this reason per MEMORY.md). These tests may need to be skipped similarly if importing `main.py` at test time fails. If so:

```python
import pytest

pytest.importorskip("main", reason="main.py requires full DB config")
```

Wrap each test in `try/except ImportError` is also acceptable. See handling in Step 3.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_company_request.py::TestIpRateLimit -v`
Expected: FAIL — either AttributeError `_check_org_request_rate_limit` not found, or import skip.

- [ ] **Step 3: Add the rate-limit helper**

In `backend/main.py`, locate the rate-limit constants (around line 258) and add:

```python
# Rate limiting for org creation request (per IP)
_ORG_REQUEST_LIMIT = 5  # max requests per IP per window
_ORG_REQUEST_WINDOW = 3600  # 1 hour in seconds
_org_request_rate_limit_fallback = {}
```

Then, near `_check_api_rate_limit` (around line 268), add:

```python
def _check_org_request_rate_limit(ip: str) -> bool:
    """
    Check if IP has exceeded rate limit for org creation requests.
    Returns True if allowed, False if rate limited.
    Increments counter on every call (unlike _check_auth_rate_limit which
    only counts failures).
    """
    key = f"rate_limit:org_request:{ip}"

    if redis_client:
        try:
            current = redis_client.get(key)
            current = int(current) if current else 0
            if current >= _ORG_REQUEST_LIMIT:
                return False
            pipe = redis_client.pipeline()
            pipe.incr(key)
            pipe.expire(key, _ORG_REQUEST_WINDOW)
            pipe.execute()
            return True
        except Exception as e:
            logger.error(f"Redis org_request rate limit failed: {e}. Using fallback.")

    # Fallback to in-memory
    now = time.time()
    attempts = _org_request_rate_limit_fallback.get(ip, [])
    attempts = [t for t in attempts if now - t < _ORG_REQUEST_WINDOW]
    if len(attempts) >= _ORG_REQUEST_LIMIT:
        return False
    attempts.append(now)
    _org_request_rate_limit_fallback[ip] = attempts
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_company_request.py::TestIpRateLimit -v`
Expected: 3 passed, or 3 skipped if `main.py` import fails in unit test context (acceptable — manual testing covers).

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_company_request.py
git commit -m "feat(main): add IP rate limit for org creation requests"
```

---

## Task 7: Add environment variable and URL helper

**Files:**
- Modify: `backend/.env.example`
- Modify: `backend/main.py` (add a helper near the top constants)

- [ ] **Step 1: Update `.env.example`**

Append to `backend/.env.example`:

```bash

# Email recipient for organization creation requests (manual approval workflow)
ADMIN_NOTIFICATION_EMAIL=jeremy@taic.co

# Public base URL of the backend (used for building magic links in emails)
# In production: https://backend-xxx.run.app (Cloud Run URL)
BACKEND_PUBLIC_URL=http://localhost:8080

# Public base URL of the frontend (used for user-facing links in emails)
FRONTEND_PUBLIC_URL=http://localhost:3000
```

- [ ] **Step 2: Add helper constants in main.py**

In `backend/main.py`, near other env-based config (grep for `os.getenv`), add:

```python
ADMIN_NOTIFICATION_EMAIL = os.getenv("ADMIN_NOTIFICATION_EMAIL", "jeremy@taic.co")
BACKEND_PUBLIC_URL = os.getenv("BACKEND_PUBLIC_URL", "http://localhost:8080").rstrip("/")
FRONTEND_PUBLIC_URL = os.getenv("FRONTEND_PUBLIC_URL", "http://localhost:3000").rstrip("/")
```

- [ ] **Step 3: Commit**

```bash
git add backend/.env.example backend/main.py
git commit -m "feat(config): add env vars for admin notification and public URLs"
```

---

## Task 8: Implement `POST /api/companies/request`

**Files:**
- Modify: `backend/main.py` (add new endpoint near the existing `create_company` at line 4714)

- [ ] **Step 1: Add the endpoint**

In `backend/main.py`, add the following endpoint immediately BEFORE the existing `@app.post("/api/companies")` endpoint (so they are colocated; we will delete the old one in Task 13):

```python
@app.post("/api/companies/request")
async def create_company_request(
    request: Request,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Submit a request to create a new organization. Requires manual approval."""
    import secrets as _secrets
    from validation import CompanyRequestCreateValidated
    from email_service import send_email, render_admin_org_request_email

    # Rate limit by IP
    client_ip = request.client.host if request.client else "unknown"
    if not _check_org_request_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Trop de demandes, réessayez dans une heure",
        )

    # Parse + validate body
    body = await request.json()
    try:
        validated = CompanyRequestCreateValidated(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    name = validated.name

    uid = int(user_id)

    # User must not already be in an org
    if db.query(CompanyMembership).filter(CompanyMembership.user_id == uid).first():
        raise HTTPException(
            status_code=409,
            detail="Vous êtes déjà membre d'une organisation",
        )

    # User must not already have a pending request
    existing_pending = (
        db.query(CompanyCreationRequest)
        .filter(
            CompanyCreationRequest.user_id == uid,
            CompanyCreationRequest.status == "pending",
        )
        .first()
    )
    if existing_pending:
        raise HTTPException(
            status_code=409,
            detail="Une demande est déjà en cours d'examen",
        )

    # Create the request
    token = _secrets.token_urlsafe(48)
    req = CompanyCreationRequest(
        user_id=uid,
        requested_name=name,
        status="pending",
        token=token,
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    # Fetch requester info for the email
    user = db.query(User).filter(User.id == uid).first()
    requester_email = user.email if user else "inconnu"

    # Build magic links
    approve_url = f"{BACKEND_PUBLIC_URL}/api/admin/companies/request/{token}?action=approve"
    reject_url = f"{BACKEND_PUBLIC_URL}/api/admin/companies/request/{token}?action=reject"

    # Send admin email (best-effort — don't fail the request if SMTP is down)
    try:
        html = render_admin_org_request_email(
            requester_email=requester_email,
            requested_name=name,
            approve_url=approve_url,
            reject_url=reject_url,
        )
        send_email(
            to=ADMIN_NOTIFICATION_EMAIL,
            subject=f"🏢 Nouvelle demande : \"{name}\" par {requester_email}",
            html_body=html,
        )
    except Exception as e:
        logger.error(f"Failed to send admin notification for org request {req.id}: {e}")

    return {
        "status": "pending",
        "requested_name": name,
    }
```

Also ensure the imports at the top of `main.py` include `CompanyCreationRequest`. Search for `from database import` and add `CompanyCreationRequest` to the list.

- [ ] **Step 2: Manual smoke test**

Run backend locally:
```bash
cd backend && python -m uvicorn main:app --reload --port 8080
```

Then in another terminal, with a valid cookie (or use the frontend login):
```bash
curl -X POST http://localhost:8080/api/companies/request \
  -H "Content-Type: application/json" \
  -H "Cookie: auth_token=..." \
  -d '{"name":"Test Org"}'
```

Expected: `{"status":"pending","requested_name":"Test Org"}`. Check DB: `SELECT * FROM company_creation_requests;` should show 1 row.

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat(api): add POST /api/companies/request endpoint"
```

---

## Task 9: Implement `GET /api/companies/request/mine`

**Files:**
- Modify: `backend/main.py` (add right after Task 8's endpoint)

- [ ] **Step 1: Add the endpoint**

In `backend/main.py`, immediately after the `create_company_request` function:

```python
@app.get("/api/companies/request/mine")
async def get_my_company_request(
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Return the user's most recent org creation request (or null)."""
    uid = int(user_id)
    req = (
        db.query(CompanyCreationRequest)
        .filter(CompanyCreationRequest.user_id == uid)
        .order_by(CompanyCreationRequest.created_at.desc())
        .first()
    )
    if not req:
        return {"request": None}
    return {
        "request": {
            "id": req.id,
            "requested_name": req.requested_name,
            "status": req.status,
            "created_at": req.created_at.isoformat() if req.created_at else None,
            "decided_at": req.decided_at.isoformat() if req.decided_at else None,
            "decided_reason": req.decided_reason,
        }
    }
```

- [ ] **Step 2: Manual smoke test**

```bash
curl http://localhost:8080/api/companies/request/mine \
  -H "Cookie: auth_token=..."
```

Expected: after Task 8, `{"request":{"id":1,"requested_name":"Test Org","status":"pending",...}}`.

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat(api): add GET /api/companies/request/mine endpoint"
```

---

## Task 10: Implement admin confirmation pages (GET)

**Files:**
- Modify: `backend/main.py` (add new endpoint after `get_my_company_request`)

- [ ] **Step 1: Add the endpoint**

In `backend/main.py`, after `get_my_company_request`:

```python
from fastapi.responses import HTMLResponse


@app.get("/api/admin/companies/request/{token}", response_class=HTMLResponse)
async def admin_org_request_confirm_page(
    token: str,
    action: str,
    db: Session = Depends(get_db),
):
    """Admin confirmation page (rendered HTML). No auth: token IS the auth.

    Shows a confirmation button to avoid accidental actions from Gmail pre-fetch.
    """
    from admin_html_pages import (
        confirm_approve_page,
        confirm_reject_page,
        error_page,
    )

    if action not in ("approve", "reject"):
        return HTMLResponse(error_page("Action inconnue."), status_code=400)

    req = db.query(CompanyCreationRequest).filter(CompanyCreationRequest.token == token).first()
    if not req:
        return HTMLResponse(error_page("Cette demande n'existe pas."), status_code=404)

    if req.status != "pending":
        return HTMLResponse(
            error_page(f"Cette demande a déjà été traitée (statut : {req.status})."),
            status_code=410,
        )

    user = db.query(User).filter(User.id == req.user_id).first()
    requester_email = user.email if user else "inconnu"

    post_url = f"{BACKEND_PUBLIC_URL}/api/admin/companies/request/{token}/decide"

    if action == "approve":
        return HTMLResponse(
            confirm_approve_page(token, requester_email, req.requested_name, post_url)
        )
    else:
        return HTMLResponse(
            confirm_reject_page(token, requester_email, req.requested_name, post_url)
        )
```

- [ ] **Step 2: Manual smoke test**

In browser, visit:
```
http://localhost:8080/api/admin/companies/request/<token>?action=approve
```
(where `<token>` is from the request row created in Task 8).

Expected: HTML page with the org name and "Confirmer l'approbation" button. Click Cancel link works; form submit action points to `/decide` (will 404 until Task 11).

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat(api): add admin GET confirmation page for org requests"
```

---

## Task 11: Implement admin decision endpoint (POST)

**Files:**
- Modify: `backend/main.py` (add after Task 10)

- [ ] **Step 1: Add the endpoint**

In `backend/main.py`, after `admin_org_request_confirm_page`:

```python
@app.post("/api/admin/companies/request/{token}/decide", response_class=HTMLResponse)
async def admin_org_request_decide(
    token: str,
    action: str = Form(...),
    reason: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Execute the admin decision (approve/reject). No auth: token is the auth."""
    import secrets as _secrets
    from admin_html_pages import success_page, error_page
    from email_service import (
        send_email,
        render_user_org_approved_email,
        render_user_org_rejected_email,
    )

    if action not in ("approve", "reject"):
        return HTMLResponse(error_page("Action inconnue."), status_code=400)

    req = db.query(CompanyCreationRequest).filter(CompanyCreationRequest.token == token).first()
    if not req:
        return HTMLResponse(error_page("Cette demande n'existe pas."), status_code=404)

    if req.status != "pending":
        return HTMLResponse(
            error_page(f"Cette demande a déjà été traitée (statut : {req.status})."),
            status_code=410,
        )

    user = db.query(User).filter(User.id == req.user_id).first()
    if not user:
        req.status = "rejected"
        req.decided_at = datetime.utcnow()
        req.decided_reason = "Utilisateur introuvable"
        db.commit()
        return HTMLResponse(error_page("Utilisateur introuvable — demande annulée."), status_code=404)

    user_app_url = f"{FRONTEND_PUBLIC_URL}/organization"

    if action == "approve":
        # Re-check name uniqueness at approval time (race condition with other orgs)
        if db.query(Company).filter(Company.name == req.requested_name).first():
            return HTMLResponse(
                error_page(
                    f"Le nom \"{req.requested_name}\" est déjà pris. "
                    "Refusez cette demande ou contactez le demandeur."
                ),
                status_code=409,
            )

        # Re-check user is not already in an org
        if db.query(CompanyMembership).filter(CompanyMembership.user_id == user.id).first():
            return HTMLResponse(
                error_page("L'utilisateur a rejoint une autre organisation entre-temps."),
                status_code=409,
            )

        # Create company + membership
        company = Company(
            name=req.requested_name,
            neo4j_enabled=True,
            invite_code=_secrets.token_urlsafe(16),
        )
        db.add(company)
        db.flush()

        membership = CompanyMembership(
            user_id=user.id,
            company_id=company.id,
            role="owner",
        )
        db.add(membership)

        # Also sync user.company_id (existing pattern in the codebase)
        user.company_id = company.id

        req.status = "approved"
        req.decided_at = datetime.utcnow()
        req.company_id = company.id
        db.commit()

        # Invalidate user cache (consistent with other user mutations)
        try:
            invalidate_user_cache(user.id)
        except Exception as e:
            logger.error(f"Failed to invalidate user cache: {e}")

        # Send approval email
        try:
            html = render_user_org_approved_email(req.requested_name, user_app_url)
            send_email(
                to=user.email,
                subject=f"✅ Votre organisation \"{req.requested_name}\" a été approuvée",
                html_body=html,
            )
        except Exception as e:
            logger.error(f"Failed to send approval email: {e}")

        return HTMLResponse(
            success_page(f"L'organisation \"{req.requested_name}\" a été créée pour {user.email}.")
        )

    else:  # reject
        cleaned_reason = (reason or "").strip() or None
        req.status = "rejected"
        req.decided_at = datetime.utcnow()
        req.decided_reason = cleaned_reason
        db.commit()

        try:
            html = render_user_org_rejected_email(
                req.requested_name, cleaned_reason, user_app_url
            )
            send_email(
                to=user.email,
                subject="Votre demande d'organisation",
                html_body=html,
            )
        except Exception as e:
            logger.error(f"Failed to send rejection email: {e}")

        return HTMLResponse(
            success_page(f"La demande pour \"{req.requested_name}\" a été refusée.")
        )
```

Ensure `from fastapi import Form` is present at the top of `main.py` (if not already imported).

- [ ] **Step 2: Manual smoke test (end-to-end)**

1. Create a fresh request via Task 8 curl command
2. Visit `http://localhost:8080/api/admin/companies/request/<token>?action=approve`
3. Click "Confirmer l'approbation"
4. Expected: success page "L'organisation has been created for ..."
5. Check DB:
   ```sql
   SELECT * FROM companies WHERE name = 'Test Org';
   SELECT * FROM company_memberships WHERE company_id = <new_id>;
   SELECT * FROM company_creation_requests ORDER BY id DESC LIMIT 1;
   ```
   Expected: new Company row, 1 owner membership, request status='approved'.
6. Try clicking the same link again → expect "déjà été traitée" error.
7. Repeat with action=reject on a fresh request → check company_creation_requests.status='rejected', no Company row created.

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat(api): add admin POST decide endpoint for org requests"
```

---

## Task 12: Harmonize terminology in error messages

**Files:**
- Modify: `backend/main.py` (sweep all `HTTPException(detail=...)` in `/api/companies/*` endpoints)

- [ ] **Step 1: Audit and replace**

Search `backend/main.py` for all `HTTPException` in the `@app.*("/api/companies/*"` routes and normalize user-facing strings to use "organisation" (French) consistently:

Specifically replace:
- `"A company with this name already exists"` → `"Une organisation avec ce nom existe déjà"`
- `"Company name is required"` → `"Le nom de l'organisation est requis"`
- `"Company not found"` → `"Organisation introuvable"`
- `"You are already a member of an organization"` → (already correct, leave as-is)
- Any other "company" → "organisation" in user-visible strings

Important: do NOT rename internal variable names, SQL table names, or function names. Only the `detail=` strings passed to HTTPException.

Use Grep to find all occurrences:
```bash
grep -n "company\|Company" backend/main.py | grep -i "detail\|HTTPException"
```

Replace manually, one at a time, to avoid over-eager replacements.

- [ ] **Step 2: Verify no regression in tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: all tests pass (none of the existing tests should rely on the exact English strings).

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "refactor(api): harmonize org error messages to French 'organisation'"
```

---

## Task 13: Delete the old `POST /api/companies` endpoint

**Files:**
- Modify: `backend/main.py` (remove the `create_company` function at line 4714)

**Note:** This task is bundled with the frontend switch (Task 14-16) in the same PR to keep the bascule atomic. Do NOT merge this task to `dev` without also merging Task 14-16.

- [ ] **Step 1: Locate and delete**

In `backend/main.py`, find:

```python
@app.post("/api/companies")
async def create_company(request: Request, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Create a company and affiliate the creator as owner."""
    ...
```

Delete the entire function (decorator + body, until the next `@app.` decorator).

- [ ] **Step 2: Verify it's gone**

Run: `grep -n "POST.*api/companies\"" backend/main.py`
Expected: only `"/api/companies/request"` appears (no bare `"/api/companies"` POST route).

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "refactor(api): remove direct POST /api/companies (replaced by request flow)"
```

---

## Task 14: Update i18n files (French)

**Files:**
- Modify: `frontend/public/locales/fr/organization.json`

- [ ] **Step 1: Add new keys**

In `frontend/public/locales/fr/organization.json`, merge the following into the existing JSON (under the existing top-level keys):

```json
{
  "noOrg": {
    "title": "Aucune organisation",
    "description": "Creez une nouvelle organisation ou rejoignez-en une avec un code d'invitation.",
    "createTitle": "Creer une organisation",
    "namePlaceholder": "Nom de l'organisation",
    "createButton": "Demander la création",
    "joinTitle": "Rejoindre avec un code",
    "codePlaceholder": "Collez le code d'invitation",
    "joinButton": "Rejoindre",
    "requestSubmitted": "Demande envoyée ! Vous recevrez un email dès qu'elle sera traitée."
  },
  "request": {
    "pendingTitle": "Demande en cours d'examen",
    "pendingBody": "Votre demande pour l'organisation \"{{name}}\" est en cours d'examen par notre équipe. Vous recevrez un email dès qu'elle sera traitée.",
    "pendingSubmittedAt": "Soumise le {{date}}",
    "rejectedTitle": "Demande refusée",
    "rejectedBody": "Votre précédente demande pour \"{{name}}\" a été refusée.",
    "rejectedReason": "Raison : {{reason}}",
    "retryButton": "Soumettre une nouvelle demande"
  }
}
```

Replace the entire `noOrg` block with the new content above (it supersedes the existing one — note the updated `createButton` and new `requestSubmitted`). Add the new `request` section.

- [ ] **Step 2: Validate JSON**

Run: `python -c "import json; json.load(open('frontend/public/locales/fr/organization.json'))"`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add frontend/public/locales/fr/organization.json
git commit -m "i18n(fr): add org creation request keys"
```

---

## Task 15: Update i18n files (English)

**Files:**
- Modify: `frontend/public/locales/en/organization.json`

- [ ] **Step 1: Add the English equivalents**

In `frontend/public/locales/en/organization.json`, merge:

```json
{
  "noOrg": {
    "title": "No organization",
    "description": "Create a new organization or join one with an invite code.",
    "createTitle": "Create an organization",
    "namePlaceholder": "Organization name",
    "createButton": "Request creation",
    "joinTitle": "Join with a code",
    "codePlaceholder": "Paste the invite code",
    "joinButton": "Join",
    "requestSubmitted": "Request submitted! You'll receive an email when it's processed."
  },
  "request": {
    "pendingTitle": "Request under review",
    "pendingBody": "Your request for organization \"{{name}}\" is under review. You'll receive an email when it's processed.",
    "pendingSubmittedAt": "Submitted on {{date}}",
    "rejectedTitle": "Request rejected",
    "rejectedBody": "Your previous request for \"{{name}}\" was rejected.",
    "rejectedReason": "Reason: {{reason}}",
    "retryButton": "Submit a new request"
  }
}
```

- [ ] **Step 2: Validate JSON**

Run: `python -c "import json; json.load(open('frontend/public/locales/en/organization.json'))"`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add frontend/public/locales/en/organization.json
git commit -m "i18n(en): add org creation request keys"
```

---

## Task 16: Update frontend `organization.js` — switch to request flow

**Files:**
- Modify: `frontend/pages/organization.js`

- [ ] **Step 1: Add state + load logic for pending/rejected requests**

At the top of the component (after existing `useState` declarations, around line 47), add:

```javascript
// Org creation request state
const [myRequest, setMyRequest] = useState(null); // { id, requested_name, status, created_at, decided_reason }
```

In the existing `loadCompany` function, after the `setCompany(data.company);` line, add:

```javascript
      // If no company, check for a pending/rejected request
      if (!data.company) {
        try {
          const reqRes = await api.get('/api/companies/request/mine');
          setMyRequest(reqRes.data.request);
        } catch {
          setMyRequest(null);
        }
      } else {
        setMyRequest(null);
      }
```

- [ ] **Step 2: Replace `handleCreate` to call the new endpoint**

Find the existing `handleCreate` function (around line 127) and replace its body:

```javascript
  const handleCreate = async () => {
    if (!createName.trim()) return;
    setActionLoading(true);
    try {
      await api.post('/api/companies/request', { name: createName.trim() });
      toast.success(t('organization:noOrg.requestSubmitted'));
      setCreateName('');
      // Refresh to show pending state
      loadCompany();
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:errors.generic'));
    } finally {
      setActionLoading(false);
    }
  };
```

- [ ] **Step 3: Add render logic for pending/rejected states**

Find the `{/* ======== NO ORG ======== */}` block (around line 380) and replace it with:

```javascript
          {/* ======== NO ORG ======== */}
          {!company && myRequest?.status === 'pending' && (
            <div className="bg-white rounded-card shadow-card border border-gray-200 p-8 max-w-2xl mx-auto text-center">
              <div className="w-16 h-16 rounded-full bg-gradient-to-br from-amber-400 to-amber-600 flex items-center justify-center mx-auto mb-4">
                <Loader2 className="w-8 h-8 text-white animate-spin" />
              </div>
              <h2 className="text-xl font-heading font-bold text-gray-900 mb-3">
                {t('organization:request.pendingTitle')}
              </h2>
              <p className="text-gray-600 mb-4">
                {t('organization:request.pendingBody', { name: myRequest.requested_name })}
              </p>
              {myRequest.created_at && (
                <p className="text-sm text-gray-400">
                  {t('organization:request.pendingSubmittedAt', {
                    date: new Date(myRequest.created_at).toLocaleDateString()
                  })}
                </p>
              )}
            </div>
          )}

          {!company && myRequest?.status === 'rejected' && (
            <div className="bg-white rounded-card shadow-card border border-gray-200 p-8 max-w-2xl mx-auto">
              <div className="flex flex-col items-center text-center mb-6">
                <div className="w-16 h-16 rounded-full bg-gradient-to-br from-red-400 to-red-600 flex items-center justify-center mb-4">
                  <XCircle className="w-8 h-8 text-white" />
                </div>
                <h2 className="text-xl font-heading font-bold text-gray-900 mb-3">
                  {t('organization:request.rejectedTitle')}
                </h2>
                <p className="text-gray-600 mb-2">
                  {t('organization:request.rejectedBody', { name: myRequest.requested_name })}
                </p>
                {myRequest.decided_reason && (
                  <p className="text-sm text-gray-500 p-3 bg-red-50 border-l-3 border-red-400 rounded mt-3">
                    {t('organization:request.rejectedReason', { reason: myRequest.decided_reason })}
                  </p>
                )}
              </div>
              <button
                onClick={() => setMyRequest(null)}
                className="w-full py-3 bg-gradient-to-r from-teal-500 to-teal-600 hover:from-teal-600 hover:to-teal-700 text-white font-semibold rounded-button shadow-card hover:shadow-elevated transition-all"
              >
                {t('organization:request.retryButton')}
              </button>
            </div>
          )}

          {!company && !myRequest && (
            <div className="grid md:grid-cols-2 gap-6">
              {/* Create */}
              <div className="bg-white rounded-card shadow-card border border-gray-200 p-8">
                <div className="flex items-center space-x-3 mb-6">
                  <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-teal-400 to-teal-600 flex items-center justify-center">
                    <Building2 className="w-5 h-5 text-white" />
                  </div>
                  <h2 className="text-xl font-heading font-bold text-gray-900">{t('organization:noOrg.createTitle')}</h2>
                </div>
                <input
                  type="text" className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-teal-500 focus:ring-2 focus:ring-teal-200 transition-all outline-none bg-white mb-4"
                  placeholder={t('organization:noOrg.namePlaceholder')} value={createName} onChange={e => setCreateName(e.target.value)}
                />
                <button onClick={handleCreate} disabled={actionLoading || !createName.trim()}
                  className="w-full py-3 bg-gradient-to-r from-teal-500 to-teal-600 hover:from-teal-600 hover:to-teal-700 text-white font-semibold rounded-button shadow-card hover:shadow-elevated disabled:opacity-50 disabled:cursor-not-allowed transition-all">
                  {actionLoading ? <Loader2 className="w-5 h-5 animate-spin mx-auto" /> : t('organization:noOrg.createButton')}
                </button>
              </div>

              {/* Join */}
              <div className="bg-white rounded-card shadow-card border border-gray-200 p-8">
                <div className="flex items-center space-x-3 mb-6">
                  <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-400 to-blue-600 flex items-center justify-center">
                    <UserPlus className="w-5 h-5 text-white" />
                  </div>
                  <h2 className="text-xl font-heading font-bold text-gray-900">{t('organization:noOrg.joinTitle')}</h2>
                </div>
                <input
                  type="text" className="w-full px-4 py-3 border border-gray-200 rounded-input focus:border-blue-500 focus:ring-2 focus:ring-blue-200 transition-all outline-none bg-white mb-4"
                  placeholder={t('organization:noOrg.codePlaceholder')} value={joinCode} onChange={e => setJoinCode(e.target.value)}
                />
                <button onClick={handleJoin} disabled={actionLoading || !joinCode.trim()}
                  className="w-full py-3 bg-gradient-to-r from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700 text-white font-semibold rounded-button shadow-card hover:shadow-elevated disabled:opacity-50 disabled:cursor-not-allowed transition-all">
                  {actionLoading ? <Loader2 className="w-5 h-5 animate-spin mx-auto" /> : t('organization:noOrg.joinButton')}
                </button>
              </div>
            </div>
          )}
```

Note: The third condition `!myRequest` shows the Create/Join UI only when the user has no request in state. Flow:
- No request ever → Create/Join form (3rd block)
- Pending request → pending panel (1st block)
- Rejected request → rejected panel with "retry" button (2nd block). Clicking retry calls `setMyRequest(null)`, which hides the rejected panel and shows the Create/Join form again. Once a new request is created and `loadCompany()` re-fetches, `myRequest` gets repopulated with the new `pending` one.

Also ensure `XCircle` is imported at the top: the existing imports around line 32 already include several `lucide-react` icons; add `XCircle` to that list.

- [ ] **Step 4: Build and visually test**

Run:
```bash
cd frontend && npm run build
```
Expected: build succeeds.

Run dev server:
```bash
cd frontend && npm run dev
```

Visit `http://localhost:3000/organization` with:
- A user without a request → see the two-card Create/Join layout
- After clicking Create → toast "Demande envoyée !" + page switches to "en cours d'examen"
- Refresh → still shows pending
- In another browser session, manually approve via `http://localhost:8080/api/admin/companies/request/<token>?action=approve` → back in the user tab, refresh → now shows the full org management UI

- [ ] **Step 5: Commit**

```bash
git add frontend/pages/organization.js
git commit -m "feat(frontend): add org creation request flow (pending/rejected states)"
```

---

## Task 17: Final integration smoke test

- [ ] **Step 1: Run all backend tests**

```bash
cd backend && python -m pytest -v
```
Expected: all tests pass (or skip cleanly).

- [ ] **Step 2: Run lint**

```bash
cd backend && ruff check .
cd frontend && npm run lint
```
Expected: no errors.

- [ ] **Step 3: Run frontend build**

```bash
cd frontend && npm run build
```
Expected: build succeeds.

- [ ] **Step 4: End-to-end manual test (French + English)**

1. Register a new user via `/login`
2. Navigate to `/organization`
3. Submit a request for "Test Org FR"
4. Switch to English locale → verify translations are correct on both languages
5. Open admin email inbox (or check logs) → confirm email was received
6. Approve via the magic link
7. Verify user sees the full org management UI
8. Check emails: user received "approved" email
9. Repeat for rejected case with a different user

- [ ] **Step 5: If all good, push and open PR**

```bash
git push -u origin <branch-name>
gh pr create --title "feat: manual org creation approval flow" --body "Implements the design from docs/superpowers/specs/2026-04-16-org-creation-manual-approval-design.md"
```

Do NOT merge until Jeremy has approved the PR manually and tested in staging.
