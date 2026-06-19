"""Tests for the Google Calendar plugin."""

from unittest.mock import patch, MagicMock


class TestGoogleCalendarPlugin:
    def test_plugin_metadata(self):
        from plugins.google_calendar import GoogleCalendarPlugin

        p = GoogleCalendarPlugin()
        assert p.name == "google_calendar"
        assert p.display_name == "Google Calendar"

    def test_get_actions(self):
        from plugins.google_calendar import GoogleCalendarPlugin

        p = GoogleCalendarPlugin()
        actions = p.get_actions()
        assert "create_event" in actions
        assert "list_events" in actions
        assert "update_event" in actions

    @patch("plugins.google_calendar.actions.build")
    def test_create_event(self, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.events().insert().execute.return_value = {
            "id": "evt123",
            "htmlLink": "https://calendar.google.com/evt123",
        }
        from plugins.google_calendar import GoogleCalendarPlugin

        p = GoogleCalendarPlugin()
        result = p.execute(
            "create_event",
            {"title": "Meeting", "start": "2026-06-04T10:00:00+02:00", "end": "2026-06-04T11:00:00+02:00"},
            MagicMock(),
        )
        assert result.success is True
        assert result.data["event_id"] == "evt123"

    def test_execute_unknown_action(self):
        from plugins.google_calendar import GoogleCalendarPlugin

        p = GoogleCalendarPlugin()
        result = p.execute("unknown", {}, None)
        assert result.success is False
