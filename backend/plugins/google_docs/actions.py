"""Google Docs action implementations."""

from __future__ import annotations

import logging

from googleapiclient.discovery import build
from plugins.base import ActionResult

logger = logging.getLogger(__name__)


def create_doc(args: dict, credentials) -> ActionResult:
    """Create a new Google Doc."""
    title = args.get("title", "Untitled Document")
    content = args.get("content")

    try:
        service = build("docs", "v1", credentials=credentials)
        doc = service.documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]

        if content:
            requests = [{"insertText": {"location": {"index": 1}, "text": content}}]
            service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

        url = f"https://docs.google.com/document/d/{doc_id}/edit"
        return ActionResult(
            success=True,
            data={"document_id": doc_id, "url": url},
            display_message=f"Created Google Doc '{title}'",
            resource_url=url,
            error_message=None,
        )
    except Exception as e:
        logger.exception(f"Failed to create Google Doc: {e}")
        return ActionResult(
            success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to create document: {e}"
        )


def update_doc(args: dict, credentials) -> ActionResult:
    """Append content to an existing Google Doc."""
    doc_id = args.get("doc_id")
    content = args.get("content", "")

    try:
        service = build("docs", "v1", credentials=credentials)
        doc = service.documents().get(documentId=doc_id).execute()
        end_index = doc["body"]["content"][-1]["endIndex"] - 1

        requests = [{"insertText": {"location": {"index": end_index}, "text": "\n" + content}}]
        service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

        url = f"https://docs.google.com/document/d/{doc_id}/edit"
        return ActionResult(
            success=True,
            data={"document_id": doc_id, "url": url},
            display_message=f"Updated Google Doc",
            resource_url=url,
            error_message=None,
        )
    except Exception as e:
        logger.exception(f"Failed to update Google Doc: {e}")
        return ActionResult(
            success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to update document: {e}"
        )


def share_doc(args: dict, credentials) -> ActionResult:
    """Share a Google Doc with a user."""
    doc_id = args.get("doc_id")
    email = args.get("email")
    role = args.get("role", "reader")

    try:
        drive_service = build("drive", "v3", credentials=credentials)
        drive_service.permissions().create(
            fileId=doc_id,
            body={"type": "user", "role": role, "emailAddress": email},
            sendNotificationEmail=True,
        ).execute()

        url = f"https://docs.google.com/document/d/{doc_id}/edit"
        return ActionResult(
            success=True,
            data={"document_id": doc_id, "shared_with": email, "role": role},
            display_message=f"Shared document with {email} as {role}",
            resource_url=url,
            error_message=None,
        )
    except Exception as e:
        logger.exception(f"Failed to share Google Doc: {e}")
        return ActionResult(
            success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to share document: {e}"
        )
