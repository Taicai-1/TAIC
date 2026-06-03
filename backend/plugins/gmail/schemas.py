"""Function calling schemas for Gmail actions."""

SEND_EMAIL = {
    "type": "object",
    "properties": {
        "to": {"type": "string", "description": "Recipient email address"},
        "subject": {"type": "string", "description": "Email subject line"},
        "body": {"type": "string", "description": "Email body text"},
        "cc": {"type": "string", "description": "CC email addresses, comma-separated"},
        "bcc": {"type": "string", "description": "BCC email addresses, comma-separated"},
    },
    "required": ["to", "subject", "body"],
}

REPLY_EMAIL = {
    "type": "object",
    "properties": {
        "thread_id": {"type": "string", "description": "Gmail thread ID to reply to"},
        "body": {"type": "string", "description": "Reply body text"},
    },
    "required": ["thread_id", "body"],
}

SEARCH_EMAILS = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Gmail search query (same syntax as Gmail search)"},
        "max_results": {"type": "integer", "description": "Maximum number of results (default: 10)"},
    },
    "required": ["query"],
}
