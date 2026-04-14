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
            password="TestPass1",
        )
        assert user.username == "testuser"
        assert user.email == "test@example.com"

    def test_short_password_rejected(self):
        with pytest.raises(ValidationError):
            UserCreateValidated(
                username="testuser",
                email="test@example.com",
                password="short",
            )

    def test_no_uppercase_rejected(self):
        with pytest.raises(ValidationError):
            UserCreateValidated(
                username="testuser",
                email="test@example.com",
                password="alllowercase1",
            )

    def test_invalid_email_rejected(self):
        with pytest.raises(ValidationError):
            UserCreateValidated(
                username="testuser",
                email="not-valid",
                password="TestPass1",
            )

    def test_special_chars_in_username_rejected(self):
        with pytest.raises(ValidationError):
            UserCreateValidated(
                username="user<script>",
                email="test@example.com",
                password="TestPass1",
            )
