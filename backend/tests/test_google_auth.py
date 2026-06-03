"""Tests for Google OAuth2 credential management."""

import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta


class TestCheckScopesCovered:
    def test_all_scopes_covered(self):
        from google_credentials import check_scopes_covered

        granted = ["https://www.googleapis.com/auth/documents", "https://www.googleapis.com/auth/drive.file"]
        required = ["https://www.googleapis.com/auth/documents"]
        assert check_scopes_covered(granted, required) is True

    def test_missing_scopes(self):
        from google_credentials import check_scopes_covered

        granted = ["https://www.googleapis.com/auth/documents"]
        required = ["https://www.googleapis.com/auth/gmail.send"]
        assert check_scopes_covered(granted, required) is False

    def test_empty_required(self):
        from google_credentials import check_scopes_covered

        assert check_scopes_covered([], []) is True

    def test_empty_granted_nonempty_required(self):
        from google_credentials import check_scopes_covered

        assert check_scopes_covered([], ["https://www.googleapis.com/auth/documents"]) is False
