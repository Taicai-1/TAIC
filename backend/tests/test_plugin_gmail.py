"""Tests for the Gmail plugin."""

from unittest.mock import patch, MagicMock


class TestGmailPlugin:
    def test_plugin_metadata(self):
        from plugins.gmail import GmailPlugin

        p = GmailPlugin()
        assert p.name == "gmail"
        assert p.display_name == "Gmail"

    def test_get_actions(self):
        from plugins.gmail import GmailPlugin

        p = GmailPlugin()
        actions = p.get_actions()
        assert "send_email" in actions
        assert "reply_email" in actions
        assert "search_emails" in actions

    @patch("plugins.gmail.actions.build")
    def test_send_email(self, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.users().messages().send().execute.return_value = {"id": "msg123"}
        from plugins.gmail import GmailPlugin

        p = GmailPlugin()
        result = p.execute("send_email", {"to": "test@example.com", "subject": "Test", "body": "Hello"}, MagicMock())
        assert result.success is True
        assert result.data["message_id"] == "msg123"

    def test_execute_unknown_action(self):
        from plugins.gmail import GmailPlugin

        p = GmailPlugin()
        result = p.execute("unknown", {}, None)
        assert result.success is False
