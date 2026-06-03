"""Tests for the Google Slides plugin."""
from unittest.mock import patch, MagicMock

class TestGoogleSlidesPlugin:
    def test_plugin_metadata(self):
        from plugins.google_slides import GoogleSlidesPlugin
        p = GoogleSlidesPlugin()
        assert p.name == "google_slides"
        assert p.display_name == "Google Slides"

    def test_get_actions(self):
        from plugins.google_slides import GoogleSlidesPlugin
        p = GoogleSlidesPlugin()
        actions = p.get_actions()
        assert "create_presentation" in actions
        assert "add_slide" in actions

    @patch("plugins.google_slides.actions.build")
    def test_create_presentation(self, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.presentations().create().execute.return_value = {"presentationId": "pres123"}
        from plugins.google_slides import GoogleSlidesPlugin
        p = GoogleSlidesPlugin()
        result = p.execute("create_presentation", {"title": "My Pres"}, MagicMock())
        assert result.success is True
        assert "pres123" in result.resource_url

    def test_execute_unknown_action(self):
        from plugins.google_slides import GoogleSlidesPlugin
        p = GoogleSlidesPlugin()
        result = p.execute("unknown", {}, None)
        assert result.success is False
