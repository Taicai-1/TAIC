"""SSE (Server-Sent Events) formatting utilities for streaming responses."""

import json


def sse_event(event_type: str, data: dict) -> str:
    """Format a Server-Sent Event string.

    Args:
        event_type: The event name (e.g. 'token', 'done', 'error').
        data: Dictionary payload to JSON-serialize in the data field.

    Returns:
        A properly formatted SSE string ending with double newline.
    """
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
