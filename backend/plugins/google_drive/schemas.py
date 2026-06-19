"""Function calling schemas for Google Drive actions."""

CREATE_FOLDER = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Folder name"},
        "parent_id": {"type": "string", "description": "Parent folder ID (optional, defaults to root)"},
    },
    "required": ["name"],
}

MOVE_FILE = {
    "type": "object",
    "properties": {
        "file_id": {"type": "string", "description": "ID of the file to move"},
        "folder_id": {"type": "string", "description": "ID of the destination folder"},
    },
    "required": ["file_id", "folder_id"],
}

SHARE_FILE = {
    "type": "object",
    "properties": {
        "file_id": {"type": "string", "description": "ID of the file to share"},
        "email": {"type": "string", "description": "Email address to share with"},
        "role": {"type": "string", "enum": ["reader", "writer", "commenter"], "description": "Permission role"},
    },
    "required": ["file_id", "email", "role"],
}

SEARCH_FILES = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Drive search query"},
        "max_results": {"type": "integer", "description": "Maximum number of results (default: 10)"},
    },
    "required": ["query"],
}
