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
        token = create_access_token({"sub": "42"}, expires_delta=timedelta(minutes=5))
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
