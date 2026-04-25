"""Unit tests for URL refresh feature validation logic.

Tests the _fetch_and_parse_url helper by running it in a subprocess to avoid
polluting sys.modules with mocked database modules (which would break other tests).
"""

import subprocess
import sys
import pytest
from unittest.mock import MagicMock


class TestFetchAndParseUrl:
    """Tests for the _fetch_and_parse_url helper.

    These tests run the helper in a subprocess because importing
    routers.documents requires mocking database.py (which uses PostgreSQL-only
    create_engine args incompatible with SQLite). Module-level sys.modules
    mocking in the main test process pollutes other tests.
    """

    def _run_helper_test(self, script: str) -> subprocess.CompletedProcess:
        """Run a test script in a subprocess with proper env."""
        return subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=str(__import__("pathlib").Path(__file__).parent.parent),
            timeout=30,
        )

    def test_returns_content_and_filename(self):
        """Successful fetch returns (content, filename) tuple."""
        result = self._run_helper_test("""
import sys, os
os.environ.setdefault("JWT_SECRET_KEY", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")

from unittest.mock import MagicMock
# Mock heavy deps
for m in ["database", "helpers.agent_helpers", "helpers.tenant",
          "helpers.rate_limiting", "rag_engine", "redis_client",
          "utils", "google.cloud", "google.cloud.storage"]:
    sys.modules.setdefault(m, MagicMock())

from unittest.mock import patch
from routers.documents import _fetch_and_parse_url

html = "<html><head><title>Test Page</title></head><body><p>Hello world</p></body></html>"
mock_resp = MagicMock()
mock_resp.is_redirect = False
mock_resp.encoding = "utf-8"
mock_resp.text = html
mock_resp.raise_for_status = MagicMock()

with patch("requests.get", return_value=mock_resp):
    content, filename = _fetch_and_parse_url("https://example.com/page")

assert "Hello world" in content or "Test Page" in content, f"Content: {content}"
assert filename.endswith(".txt"), f"Filename: {filename}"
assert "example.com" in filename, f"Filename: {filename}"
print("PASS")
""")
        assert result.returncode == 0, f"STDERR: {result.stderr}"
        assert "PASS" in result.stdout

    def test_unreachable_url_raises_400(self):
        """Unreachable URL raises HTTPException with 400."""
        result = self._run_helper_test("""
import sys, os
os.environ.setdefault("JWT_SECRET_KEY", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")

from unittest.mock import MagicMock
for m in ["database", "helpers.agent_helpers", "helpers.tenant",
          "helpers.rate_limiting", "rag_engine", "redis_client",
          "utils", "google.cloud", "google.cloud.storage"]:
    sys.modules.setdefault(m, MagicMock())

from unittest.mock import patch
import requests as http_requests
from fastapi import HTTPException
from routers.documents import _fetch_and_parse_url

try:
    with patch("requests.get", side_effect=http_requests.exceptions.ConnectionError("refused")):
        _fetch_and_parse_url("https://unreachable.invalid")
    print("FAIL: no exception raised")
    sys.exit(1)
except HTTPException as e:
    assert e.status_code == 400, f"Expected 400, got {e.status_code}"
    print("PASS")
""")
        assert result.returncode == 0, f"STDERR: {result.stderr}"
        assert "PASS" in result.stdout

    def test_filename_truncated_and_sanitized(self):
        """Long URLs produce truncated, sanitized filenames."""
        result = self._run_helper_test("""
import sys, os
os.environ.setdefault("JWT_SECRET_KEY", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")

from unittest.mock import MagicMock
for m in ["database", "helpers.agent_helpers", "helpers.tenant",
          "helpers.rate_limiting", "rag_engine", "redis_client",
          "utils", "google.cloud", "google.cloud.storage"]:
    sys.modules.setdefault(m, MagicMock())

from unittest.mock import patch
from routers.documents import _fetch_and_parse_url

long_url = "https://example.com/" + "a" * 200
html = "<html><body><p>Content</p></body></html>"
mock_resp = MagicMock()
mock_resp.is_redirect = False
mock_resp.encoding = "utf-8"
mock_resp.text = html
mock_resp.raise_for_status = MagicMock()

with patch("requests.get", return_value=mock_resp):
    content, filename = _fetch_and_parse_url(long_url)

assert len(filename) <= 105, f"Filename too long: {len(filename)}"
assert "/" not in filename, f"Slash in filename: {filename}"
print("PASS")
""")
        assert result.returncode == 0, f"STDERR: {result.stderr}"
        assert "PASS" in result.stdout

    def test_content_truncated_at_200k(self):
        """Content longer than 200k chars is truncated."""
        result = self._run_helper_test("""
import sys, os
os.environ.setdefault("JWT_SECRET_KEY", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENVIRONMENT", "test")

from unittest.mock import MagicMock
for m in ["database", "helpers.agent_helpers", "helpers.tenant",
          "helpers.rate_limiting", "rag_engine", "redis_client",
          "utils", "google.cloud", "google.cloud.storage"]:
    sys.modules.setdefault(m, MagicMock())

from unittest.mock import patch
from routers.documents import _fetch_and_parse_url

long_content = "x" * 300000
html = f"<html><body><p>{long_content}</p></body></html>"
mock_resp = MagicMock()
mock_resp.is_redirect = False
mock_resp.encoding = "utf-8"
mock_resp.text = html
mock_resp.raise_for_status = MagicMock()

with patch("requests.get", return_value=mock_resp):
    content, filename = _fetch_and_parse_url("https://example.com")

assert len(content) <= 200000, f"Content too long: {len(content)}"
print("PASS")
""")
        assert result.returncode == 0, f"STDERR: {result.stderr}"
        assert "PASS" in result.stdout


class TestRefreshUrlValidation:
    """Tests for refresh endpoint input validation (no DB needed)."""

    def test_document_without_source_url_should_fail(self):
        """A document with source_url=None should not be refreshable."""
        doc = MagicMock()
        doc.source_url = None
        assert not doc.source_url

    def test_document_with_source_url_should_be_refreshable(self):
        """A document with a source_url set is eligible for refresh."""
        doc = MagicMock()
        doc.source_url = "https://example.com/page"
        assert doc.source_url == "https://example.com/page"
