"""Gmail action implementations."""

from __future__ import annotations
import base64
import logging
from email.mime.text import MIMEText
from googleapiclient.discovery import build
from plugins.base import ActionResult

logger = logging.getLogger(__name__)


def send_email(args: dict, credentials) -> ActionResult:
    to = args.get("to", "")
    subject = args.get("subject", "")
    body = args.get("body", "")
    cc = args.get("cc")
    bcc = args.get("bcc")
    try:
        msg = MIMEText(body)
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        if bcc:
            msg["Bcc"] = bcc
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service = build("gmail", "v1", credentials=credentials)
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return ActionResult(
            success=True,
            data={"message_id": sent["id"]},
            display_message=f"Email sent to {to}",
            resource_url=None,
            error_message=None,
        )
    except Exception as e:
        logger.exception(f"Failed to send email: {e}")
        return ActionResult(
            success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to send email: {e}"
        )


def reply_email(args: dict, credentials) -> ActionResult:
    thread_id = args.get("thread_id")
    body = args.get("body", "")
    try:
        service = build("gmail", "v1", credentials=credentials)
        # Get the original thread to find the subject and from
        thread = service.users().threads().get(userId="me", id=thread_id).execute()
        messages = thread.get("messages", [])
        if not messages:
            return ActionResult(
                success=False, data={}, display_message="", resource_url=None, error_message="Thread not found or empty"
            )
        last_msg = messages[-1]
        headers = {h["name"]: h["value"] for h in last_msg.get("payload", {}).get("headers", [])}
        subject = headers.get("Subject", "")
        if not subject.startswith("Re:"):
            subject = f"Re: {subject}"
        reply_to = headers.get("From", "")

        msg = MIMEText(body)
        msg["To"] = reply_to
        msg["Subject"] = subject
        msg["In-Reply-To"] = headers.get("Message-Id", "")
        msg["References"] = headers.get("Message-Id", "")
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        sent = service.users().messages().send(userId="me", body={"raw": raw, "threadId": thread_id}).execute()
        return ActionResult(
            success=True,
            data={"message_id": sent["id"], "thread_id": thread_id},
            display_message="Replied to thread",
            resource_url=None,
            error_message=None,
        )
    except Exception as e:
        logger.exception(f"Failed to reply to email: {e}")
        return ActionResult(
            success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to reply: {e}"
        )


def search_emails(args: dict, credentials) -> ActionResult:
    query = args.get("query", "")
    max_results = args.get("max_results", 10)
    try:
        service = build("gmail", "v1", credentials=credentials)
        results = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        messages = results.get("messages", [])
        summaries = []
        for msg_ref in messages[:max_results]:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=msg_ref["id"], format="metadata", metadataHeaders=["Subject", "From", "Date"])
                .execute()
            )
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            summaries.append(
                {
                    "id": msg["id"],
                    "subject": headers.get("Subject", ""),
                    "from": headers.get("From", ""),
                    "date": headers.get("Date", ""),
                    "snippet": msg.get("snippet", ""),
                }
            )
        return ActionResult(
            success=True,
            data={"emails": summaries, "total": len(summaries)},
            display_message=f"Found {len(summaries)} emails matching '{query}'",
            resource_url=None,
            error_message=None,
        )
    except Exception as e:
        logger.exception(f"Failed to search emails: {e}")
        return ActionResult(
            success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to search emails: {e}"
        )
