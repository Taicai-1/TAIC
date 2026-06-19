"""Function calling schemas for Google Slides actions."""

CREATE_PRESENTATION = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Presentation title"},
        "slides": {
            "type": "array",
            "description": "Slides to add",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["title"],
            },
        },
    },
    "required": ["title"],
}

ADD_SLIDE = {
    "type": "object",
    "properties": {
        "presentation_id": {"type": "string", "description": "The presentation ID"},
        "title": {"type": "string", "description": "Slide title"},
        "body": {"type": "string", "description": "Slide body text"},
    },
    "required": ["presentation_id", "title"],
}
