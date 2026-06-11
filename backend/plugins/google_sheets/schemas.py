"""Function calling schemas for Google Sheets actions."""

CREATE_SHEET = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Title of the spreadsheet"},
        "sheets": {
            "type": "array",
            "description": "Optional list of sheets to create",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "headers": {"type": "array", "items": {"type": "string"}},
                    "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                },
                "required": ["name"],
            },
        },
    },
    "required": ["title"],
}

UPDATE_SHEET = {
    "type": "object",
    "properties": {
        "spreadsheet_id": {"type": "string", "description": "The spreadsheet ID"},
        "range": {"type": "string", "description": "A1 notation range (e.g., Sheet1!A1:C3)"},
        "values": {
            "type": "array",
            "items": {"type": "array", "items": {"type": "string"}},
            "description": "2D array of values",
        },
    },
    "required": ["spreadsheet_id", "range", "values"],
}

READ_SHEET = {
    "type": "object",
    "properties": {
        "spreadsheet_id": {"type": "string", "description": "The spreadsheet ID"},
        "range": {"type": "string", "description": "A1 notation range (e.g., Sheet1!A1:C3)"},
    },
    "required": ["spreadsheet_id", "range"],
}
