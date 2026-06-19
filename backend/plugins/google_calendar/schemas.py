"""Function calling schemas for Google Calendar actions."""

CREATE_EVENT = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Event title"},
        "start": {"type": "string", "description": "Start time in ISO 8601 format (e.g., 2026-06-04T10:00:00+02:00)"},
        "end": {"type": "string", "description": "End time in ISO 8601 format"},
        "attendees": {"type": "array", "items": {"type": "string"}, "description": "List of attendee email addresses"},
        "description": {"type": "string", "description": "Event description"},
    },
    "required": ["title", "start", "end"],
}

LIST_EVENTS = {
    "type": "object",
    "properties": {
        "time_min": {"type": "string", "description": "Start of time range in ISO 8601 format"},
        "time_max": {"type": "string", "description": "End of time range in ISO 8601 format"},
        "max_results": {"type": "integer", "description": "Maximum number of events (default: 10)"},
    },
    "required": ["time_min", "time_max"],
}

UPDATE_EVENT = {
    "type": "object",
    "properties": {
        "event_id": {"type": "string", "description": "The calendar event ID"},
        "title": {"type": "string", "description": "New event title"},
        "start": {"type": "string", "description": "New start time in ISO 8601 format"},
        "end": {"type": "string", "description": "New end time in ISO 8601 format"},
        "description": {"type": "string", "description": "New event description"},
    },
    "required": ["event_id"],
}
