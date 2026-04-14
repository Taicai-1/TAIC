# CI Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GitHub Actions CI pipeline with linting (Ruff + ESLint), build verification, and unit tests for the TAIC backend.

**Architecture:** Three parallel GitHub Actions jobs: `lint-backend` (Ruff), `lint-and-build-frontend` (ESLint + Next.js build), `test-backend` (pytest with mocked dependencies). Backend tests cover `auth.py` utilities, `validation.py` sanitization/models, and the `/health` endpoint via FastAPI TestClient.

**Tech Stack:** GitHub Actions, Ruff (Python linter), pytest + pytest-asyncio + httpx (backend tests), ESLint (frontend lint), Next.js build

---

### File Structure

| File | Purpose |
|------|---------|
| `.github/workflows/ci.yml` | GitHub Actions workflow (3 parallel jobs) |
| `backend/pyproject.toml` | Ruff configuration |
| `backend/requirements-dev.txt` | Dev dependencies (ruff, pytest, pytest-asyncio, httpx) |
| `backend/tests/__init__.py` | Makes tests a package |
| `backend/tests/conftest.py` | Shared fixtures (env vars, mock DB) |
| `backend/tests/test_health.py` | Health endpoint test via TestClient |
| `backend/tests/test_auth.py` | Unit tests for auth.py functions |
| `backend/tests/test_validation.py` | Unit tests for validation.py functions |

---

### Task 1: Backend Dev Dependencies

**Files:**
- Create: `backend/requirements-dev.txt`

- [ ] **Step 1: Create requirements-dev.txt**

```
-r requirements.txt
ruff
pytest
pytest-asyncio
httpx
```

- [ ] **Step 2: Verify it's valid**

Run: `cd backend && pip install -r requirements-dev.txt --dry-run 2>&1 | head -5`
Expected: Package resolution starts without errors

- [ ] **Step 3: Commit**

```bash
git add backend/requirements-dev.txt
git commit -m "ci: add backend dev dependencies (ruff, pytest, httpx)"
```

---

### Task 2: Ruff Configuration

**Files:**
- Create: `backend/pyproject.toml`

- [ ] **Step 1: Create pyproject.toml with Ruff config**

```toml
[tool.ruff]
target-version = "py311"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "W"]
ignore = [
    "E501",   # line too long (handled by formatter, not critical for existing code)
    "E722",   # bare except (existing code uses this)
    "F401",   # unused imports (too many in existing code to fix now)
    "F841",   # unused variable (existing code)
    "W605",   # invalid escape sequence (existing code)
    "E711",   # comparison to None (existing SQLAlchemy patterns like == None)
    "E712",   # comparison to True/False (existing SQLAlchemy patterns)
    "F811",   # redefined unused (re-imports in main.py)
    "E741",   # ambiguous variable name
]

[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Verify Ruff runs on the backend**

Run: `cd backend && ruff check . --statistics 2>&1 | tail -10`
Expected: Either clean or only warnings from ignored rules. No crash.

- [ ] **Step 3: Fix any remaining Ruff errors that aren't ignored**

If ruff reports errors not in the ignore list, add them to ignore or fix the code. The goal: `ruff check .` exits 0.

Run: `cd backend && ruff check . && echo "OK"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml
git commit -m "ci: add Ruff linter configuration for backend"
```

---

### Task 3: Test Infrastructure (conftest + test_health)

**Files:**
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_health.py`

- [ ] **Step 1: Create tests/__init__.py**

Empty file:
```python
```

- [ ] **Step 2: Create conftest.py with environment setup**

The backend's `auth.py` calls `get_jwt_secret()` at module import time, which reads `JWT_SECRET_KEY` env var and raises RuntimeError if missing. We must set this BEFORE any backend module is imported.

```python
import os

# Set required env vars BEFORE any backend imports
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-ci")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")
```

- [ ] **Step 3: Write test_health.py**

```python
"""Test the /health endpoint."""
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_expected_body():
    response = client.get("/health")
    data = response.json()
    assert data["status"] == "healthy"
    assert "service" in data
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && python -m pytest tests/test_health.py -v`
Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tests/
git commit -m "ci: add test infrastructure and health endpoint tests"
```

---

### Task 4: Auth Unit Tests

**Files:**
- Create: `backend/tests/test_auth.py`

- [ ] **Step 1: Write test_auth.py**

These test `auth.py` functions directly — no HTTP calls, no DB needed.

```python
"""Unit tests for auth.py functions."""
import pytest
from datetime import timedelta
from unittest.mock import MagicMock
from fastapi import HTTPException

from auth import (
    hash_password,
    verify_password,
    create_access_token,
    verify_token,
    _decode_token,
    _extract_token,
    ALGORITHM,
    SECRET_KEY,
)


class TestPasswordHashing:
    def test_hash_password_returns_string(self):
        hashed = hash_password("TestPass1")
        assert isinstance(hashed, str)
        assert hashed != "TestPass1"

    def test_verify_password_correct(self):
        hashed = hash_password("TestPass1")
        assert verify_password("TestPass1", hashed) is True

    def test_verify_password_wrong(self):
        hashed = hash_password("TestPass1")
        assert verify_password("WrongPass1", hashed) is False


class TestJWT:
    def test_create_and_decode_token(self):
        token = create_access_token({"sub": "42"})
        payload = _decode_token(token)
        assert payload["sub"] == "42"

    def test_create_token_with_custom_expiry(self):
        token = create_access_token(
            {"sub": "42"}, expires_delta=timedelta(minutes=5)
        )
        payload = _decode_token(token)
        assert payload["sub"] == "42"

    def test_decode_invalid_token_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            _decode_token("not-a-valid-token")
        assert exc_info.value.status_code == 401


class TestExtractToken:
    def test_extract_from_cookie(self):
        request = MagicMock()
        request.cookies = {"token": "my-cookie-token"}
        request.headers = {}
        assert _extract_token(request) == "my-cookie-token"

    def test_extract_from_auth_header(self):
        request = MagicMock()
        request.cookies = {}
        request.headers = {"Authorization": "Bearer my-header-token"}
        assert _extract_token(request) == "my-header-token"

    def test_extract_no_token_raises(self):
        request = MagicMock()
        request.cookies = {}
        request.headers = {}
        with pytest.raises(HTTPException) as exc_info:
            _extract_token(request)
        assert exc_info.value.status_code == 401


class TestVerifyToken:
    def test_verify_valid_token_from_cookie(self):
        token = create_access_token({"sub": "42"})
        request = MagicMock()
        request.cookies = {"token": token}
        request.headers = {}
        user_id = verify_token(request)
        assert user_id == "42"

    def test_verify_rejects_pre_2fa_token(self):
        token = create_access_token({"sub": "42", "type": "pre_2fa"})
        request = MagicMock()
        request.cookies = {"token": token}
        request.headers = {}
        with pytest.raises(HTTPException) as exc_info:
            verify_token(request)
        assert exc_info.value.status_code == 403
```

- [ ] **Step 2: Run the tests**

Run: `cd backend && python -m pytest tests/test_auth.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_auth.py
git commit -m "ci: add auth unit tests (password hashing, JWT, token extraction)"
```

---

### Task 5: Validation Unit Tests

**Files:**
- Create: `backend/tests/test_validation.py`

- [ ] **Step 1: Write test_validation.py**

```python
"""Unit tests for validation.py sanitization and validation functions."""
import pytest
from pydantic import ValidationError

from validation import (
    sanitize_html,
    sanitize_filename,
    sanitize_text,
    check_sql_injection_attempt,
    validate_file_extension,
    validate_file_size,
    validate_email_format,
    UserCreateValidated,
)


class TestSanitizeHtml:
    def test_removes_script_tags(self):
        result = sanitize_html('<script>alert("xss")</script>Hello')
        assert "<script>" not in result
        assert "Hello" in result

    def test_removes_html_tags(self):
        result = sanitize_html("<b>bold</b> text")
        assert "<b>" not in result
        assert "bold" in result
        assert "text" in result

    def test_none_returns_none(self):
        assert sanitize_html(None) is None

    def test_empty_returns_empty(self):
        assert sanitize_html("") == ""


class TestSanitizeFilename:
    def test_removes_path_traversal(self):
        result = sanitize_filename("../../../etc/passwd")
        assert ".." not in result
        assert "/" not in result

    def test_removes_null_bytes(self):
        result = sanitize_filename("file\x00.txt")
        assert "\x00" not in result

    def test_keeps_safe_chars(self):
        result = sanitize_filename("my-file_v2.pdf")
        assert result == "my-file_v2.pdf"

    def test_none_returns_none(self):
        assert sanitize_filename(None) is None


class TestSanitizeText:
    def test_removes_null_bytes(self):
        result = sanitize_text("hello\x00world")
        assert "\x00" not in result

    def test_enforces_max_length(self):
        result = sanitize_text("a" * 200, max_length=50)
        assert len(result) == 50

    def test_collapses_whitespace(self):
        result = sanitize_text("hello   world")
        assert result == "hello world"


class TestSqlInjection:
    def test_detects_union_select(self):
        assert check_sql_injection_attempt("UNION SELECT * FROM users") is True

    def test_detects_drop_table(self):
        assert check_sql_injection_attempt("DROP TABLE users") is True

    def test_safe_text_passes(self):
        assert check_sql_injection_attempt("Hello world") is False

    def test_none_returns_false(self):
        assert check_sql_injection_attempt(None) is False


class TestFileValidation:
    def test_valid_extension(self):
        assert validate_file_extension("document.pdf") is True

    def test_invalid_extension(self):
        assert validate_file_extension("malware.exe") is False

    def test_no_extension(self):
        assert validate_file_extension("noextension") is False

    def test_valid_file_size(self):
        assert validate_file_size(1024) is True

    def test_too_large_file(self):
        assert validate_file_size(100 * 1024 * 1024) is False

    def test_zero_size(self):
        assert validate_file_size(0) is False


class TestEmailValidation:
    def test_valid_email(self):
        assert validate_email_format("user@example.com") is True

    def test_invalid_email(self):
        assert validate_email_format("not-an-email") is False


class TestUserCreateValidated:
    def test_valid_user(self):
        user = UserCreateValidated(
            username="testuser",
            email="test@example.com",
            password="TestPass1"
        )
        assert user.username == "testuser"
        assert user.email == "test@example.com"

    def test_short_password_rejected(self):
        with pytest.raises(ValidationError):
            UserCreateValidated(
                username="testuser",
                email="test@example.com",
                password="short"
            )

    def test_no_uppercase_rejected(self):
        with pytest.raises(ValidationError):
            UserCreateValidated(
                username="testuser",
                email="test@example.com",
                password="alllowercase1"
            )

    def test_invalid_email_rejected(self):
        with pytest.raises(ValidationError):
            UserCreateValidated(
                username="testuser",
                email="not-valid",
                password="TestPass1"
            )

    def test_special_chars_in_username_rejected(self):
        with pytest.raises(ValidationError):
            UserCreateValidated(
                username="user<script>",
                email="test@example.com",
                password="TestPass1"
            )
```

- [ ] **Step 2: Run the tests**

Run: `cd backend && python -m pytest tests/test_validation.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_validation.py
git commit -m "ci: add validation unit tests (sanitization, file validation, pydantic models)"
```

---

### Task 6: GitHub Actions Workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create the CI workflow**

```yaml
name: CI

on:
  push:
    branches: ['**']

jobs:
  lint-backend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install Ruff
        run: pip install ruff

      - name: Ruff lint
        run: ruff check .

      - name: Ruff format check
        run: ruff format --check .

  lint-and-build-frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: '18'
          cache: 'npm'
          cache-dependency-path: frontend/package-lock.json

      - name: Install dependencies
        run: npm ci

      - name: ESLint
        run: npx next lint

      - name: Build
        run: npm run build
        env:
          NEXT_PUBLIC_API_URL: http://localhost:8080
          NEXT_PUBLIC_GOOGLE_CLIENT_ID: fake-client-id
          NEXT_PUBLIC_GA_ID: ''

  test-backend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install system dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y libpq-dev

      - name: Install dependencies
        run: pip install -r requirements-dev.txt

      - name: Run tests
        run: python -m pytest tests/ -v --tb=short
        env:
          JWT_SECRET_KEY: test-secret-key-for-ci
          DATABASE_URL: sqlite:///:memory:
          ENVIRONMENT: test
```

- [ ] **Step 2: Verify YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('YAML OK')"`
Expected: `YAML OK`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions CI workflow (lint + build + tests)"
```

---

### Task 7: Ruff Format Fix & Final Verification

**Files:**
- Modify: Various backend files (auto-formatted by Ruff)

- [ ] **Step 1: Run Ruff format check**

Run: `cd backend && ruff format --check . 2>&1 | head -20`

If files need reformatting, proceed to step 2. If clean, skip to step 4.

- [ ] **Step 2: Auto-format with Ruff**

Run: `cd backend && ruff format .`

Review the changes:
Run: `git diff --stat`

- [ ] **Step 3: Commit formatting changes**

```bash
git add backend/
git commit -m "style: auto-format backend with Ruff"
```

- [ ] **Step 4: Run full test suite locally**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 5: Run full lint suite locally**

Run: `cd backend && ruff check . && echo "Lint OK"`
Expected: `Lint OK`

---

### Task 8: Final Push & Verify CI Runs

- [ ] **Step 1: Push to trigger CI**

Run: `git push`

- [ ] **Step 2: Verify CI is running on GitHub**

Check the Actions tab on the GitHub repository. All 3 jobs should be running:
- `lint-backend`
- `lint-and-build-frontend`
- `test-backend`

- [ ] **Step 3: Fix any CI failures**

If any job fails, read the logs, fix the issue, commit, and push again.
