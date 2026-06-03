"""Tests for the Google Drive plugin."""
from unittest.mock import patch, MagicMock

class TestGoogleDrivePlugin:
    def test_plugin_metadata(self):
        from plugins.google_drive import GoogleDrivePlugin
        p = GoogleDrivePlugin()
        assert p.name == "google_drive"
        assert p.display_name == "Google Drive"

    def test_get_actions(self):
        from plugins.google_drive import GoogleDrivePlugin
        p = GoogleDrivePlugin()
        actions = p.get_actions()
        assert "create_folder" in actions
        assert "move_file" in actions
        assert "share_file" in actions
        assert "search_files" in actions

    @patch("plugins.google_drive.actions.build")
    def test_create_folder(self, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.files().create().execute.return_value = {"id": "folder123", "webViewLink": "https://drive.google.com/folder123"}
        from plugins.google_drive import GoogleDrivePlugin
        p = GoogleDrivePlugin()
        result = p.execute("create_folder", {"name": "My Folder"}, MagicMock())
        assert result.success is True
        assert result.data["folder_id"] == "folder123"

    def test_execute_unknown_action(self):
        from plugins.google_drive import GoogleDrivePlugin
        p = GoogleDrivePlugin()
        result = p.execute("unknown", {}, None)
        assert result.success is False
