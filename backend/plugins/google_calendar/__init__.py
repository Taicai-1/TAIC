"""Google Calendar plugin."""

from plugins.base import BasePlugin, ActionDefinition, ActionResult
from plugins.google_calendar import actions, schemas


class GoogleCalendarPlugin(BasePlugin):
    name = "google_calendar"
    display_name = "Google Calendar"
    description = "Create and manage Google Calendar events"
    icon = "calendar"
    required_scopes = ["https://www.googleapis.com/auth/calendar.events"]

    def get_actions(self):
        return {
            "create_event": ActionDefinition(
                name="create_event",
                description="Create a new calendar event with title, time and optional attendees",
                parameters_schema=schemas.CREATE_EVENT,
                display_name="Create Event",
                icon="calendar-plus",
                side_effect=True,
            ),
            "list_events": ActionDefinition(
                name="list_events",
                description="List calendar events in a time range",
                parameters_schema=schemas.LIST_EVENTS,
                display_name="List Events",
                icon="calendar",
                side_effect=False,
            ),
            "update_event": ActionDefinition(
                name="update_event",
                description="Update an existing calendar event",
                parameters_schema=schemas.UPDATE_EVENT,
                display_name="Update Event",
                icon="calendar-edit",
                side_effect=True,
            ),
        }

    def execute(self, action_name, args, credentials):
        action_map = {
            "create_event": actions.create_event,
            "list_events": actions.list_events,
            "update_event": actions.update_event,
        }
        fn = action_map.get(action_name)
        if not fn:
            return ActionResult(
                success=False,
                data={},
                display_message="",
                resource_url=None,
                error_message=f"Unknown action: {action_name}",
            )
        return fn(args, credentials)


plugin_class = GoogleCalendarPlugin
