"""Function calling schemas for Google Docs actions."""

CREATE_DOC = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "The title of the document"},
        "content": {"type": "string", "description": "Optional initial content for the document"},
    },
    "required": ["title"],
}

UPDATE_DOC = {
    "type": "object",
    "properties": {
        "doc_id": {"type": "string", "description": "The Google Doc document ID"},
        "content": {"type": "string", "description": "Content to append to the document"},
    },
    "required": ["doc_id", "content"],
}

SHARE_DOC = {
    "type": "object",
    "properties": {
        "doc_id": {"type": "string", "description": "The Google Doc document ID"},
        "email": {"type": "string", "description": "Email address to share with"},
        "role": {"type": "string", "enum": ["reader", "writer", "commenter"], "description": "Permission role"},
    },
    "required": ["doc_id", "email", "role"],
}
