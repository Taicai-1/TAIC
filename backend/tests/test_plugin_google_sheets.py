"""Tests for the Google Sheets plugin."""

import pytest
from unittest.mock import patch, MagicMock


class TestGoogleSheetsPlugin:
    def test_plugin_metadata(self):
        from plugins.google_sheets import GoogleSheetsPlugin

        p = GoogleSheetsPlugin()
        assert p.name == "google_sheets"
        assert p.display_name == "Google Sheets"

    def test_get_actions(self):
        from plugins.google_sheets import GoogleSheetsPlugin

        p = GoogleSheetsPlugin()
        actions = p.get_actions()
        assert "create_sheet" in actions
        assert "update_sheet" in actions
        assert "read_sheet" in actions

    @patch("plugins.google_sheets.actions.build")
    def test_create_sheet(self, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.spreadsheets().create().execute.return_value = {"spreadsheetId": "ss123"}
        from plugins.google_sheets import GoogleSheetsPlugin

        p = GoogleSheetsPlugin()
        result = p.execute("create_sheet", {"title": "Test Sheet"}, MagicMock())
        assert result.success is True
        assert "ss123" in result.resource_url

    def test_execute_unknown_action(self):
        from plugins.google_sheets import GoogleSheetsPlugin

        p = GoogleSheetsPlugin()
        result = p.execute("unknown", {}, None)
        assert result.success is False
