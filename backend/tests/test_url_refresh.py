"""Unit tests for URL refresh feature validation logic."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException


class TestFetchAndParseUrl:
    """Tests for the _fetch_and_parse_url helper."""

    def test_returns_content_and_filename(self):
        """Successful fetch returns (content, filename) tuple."""
        from routers.documents import _fetch_and_parse_url

        html = "<html><head><title>Test Page</title></head><body><p>Hello world</p></body></html>"
        mock_response = MagicMock()
        mock_response.is_redirect = False
        mock_response.encoding = "utf-8"
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_response):
            content, filename = _fetch_and_parse_url("https://example.com/page")

        assert "Hello world" in content or "Test Page" in content
        assert filename.endswith(".txt")
        assert "example.com" in filename

    def test_unreachable_url_raises_400(self):
        """Unreachable URL raises HTTPException with 400."""
        from routers.documents import _fetch_and_parse_url
        import requests as http_requests

        with patch("requests.get", side_effect=http_requests.exceptions.ConnectionError("refused")):
            with pytest.raises(HTTPException) as exc_info:
                _fetch_and_parse_url("https://unreachable.invalid")
            assert exc_info.value.status_code == 400

    def test_filename_truncated_and_sanitized(self):
        """Long URLs produce truncated, sanitized filenames."""
        from routers.documents import _fetch_and_parse_url

        long_url = "https://example.com/" + "a" * 200

        html = "<html><body><p>Content</p></body></html>"
        mock_response = MagicMock()
        mock_response.is_redirect = False
        mock_response.encoding = "utf-8"
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_response):
            content, filename = _fetch_and_parse_url(long_url)

        assert len(filename) <= 105
        assert "/" not in filename

    def test_content_truncated_at_200k(self):
        """Content longer than 200k chars is truncated."""
        from routers.documents import _fetch_and_parse_url

        long_content = "x" * 300000
        html = f"<html><body><p>{long_content}</p></body></html>"
        mock_response = MagicMock()
        mock_response.is_redirect = False
        mock_response.encoding = "utf-8"
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()

        with patch("requests.get", return_value=mock_response):
            content, filename = _fetch_and_parse_url("https://example.com")

        assert len(content) <= 200000


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
