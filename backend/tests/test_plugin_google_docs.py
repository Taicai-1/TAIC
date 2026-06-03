"""Tests for the Google Docs plugin."""

import pytest
from unittest.mock import patch, MagicMock


class TestGoogleDocsPlugin:
    def test_plugin_metadata(self):
        from plugins.google_docs import GoogleDocsPlugin

        p = GoogleDocsPlugin()
        assert p.name == "google_docs"
        assert p.display_name == "Google Docs"
        assert len(p.required_scopes) > 0

    def test_get_actions(self):
        from plugins.google_docs import GoogleDocsPlugin

        p = GoogleDocsPlugin()
        actions = p.get_actions()
        assert "create_doc" in actions
        assert "update_doc" in actions
        assert "share_doc" in actions

    @patch("plugins.google_docs.actions.build")
    def test_create_doc(self, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.documents().create().execute.return_value = {"documentId": "doc123"}

        from plugins.google_docs import GoogleDocsPlugin

        p = GoogleDocsPlugin()
        mock_creds = MagicMock()
        result = p.execute("create_doc", {"title": "My Doc"}, mock_creds)
        assert result.success is True
        assert "doc123" in result.resource_url

    def test_execute_unknown_action(self):
        from plugins.google_docs import GoogleDocsPlugin

        p = GoogleDocsPlugin()
        result = p.execute("unknown", {}, None)
        assert result.success is False
