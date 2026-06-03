"""Google Calendar action implementations."""
from __future__ import annotations
import logging
from googleapiclient.discovery import build
from plugins.base import ActionResult

logger = logging.getLogger(__name__)

def create_event(args: dict, credentials) -> ActionResult:
    title = args.get("title", "Untitled Event")
    start = args.get("start")
    end = args.get("end")
    attendees = args.get("attendees", [])
    description = args.get("description", "")
    try:
        service = build("calendar", "v3", credentials=credentials)
        event_body = {
            "summary": title,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
        }
        if description:
            event_body["description"] = description
        if attendees:
            event_body["attendees"] = [{"email": e} for e in attendees]
        event = service.events().insert(calendarId="primary", body=event_body).execute()
        url = event.get("htmlLink", "")
        return ActionResult(success=True, data={"event_id": event["id"], "url": url},
                          display_message=f"Created event '{title}'", resource_url=url, error_message=None)
    except Exception as e:
        logger.exception(f"Failed to create event: {e}")
        return ActionResult(success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to create event: {e}")

def list_events(args: dict, credentials) -> ActionResult:
    time_min = args.get("time_min")
    time_max = args.get("time_max")
    max_results = args.get("max_results", 10)
    try:
        service = build("calendar", "v3", credentials=credentials)
        events_result = service.events().list(
            calendarId="primary", timeMin=time_min, timeMax=time_max,
            maxResults=max_results, singleEvents=True, orderBy="startTime",
        ).execute()
        events = events_result.get("items", [])
        summaries = []
        for ev in events:
            summaries.append({
                "id": ev["id"], "title": ev.get("summary", ""), "start": ev.get("start", {}).get("dateTime", ""),
                "end": ev.get("end", {}).get("dateTime", ""), "link": ev.get("htmlLink", ""),
            })
        return ActionResult(success=True, data={"events": summaries, "total": len(summaries)},
                          display_message=f"Found {len(summaries)} events", resource_url=None, error_message=None)
    except Exception as e:
        logger.exception(f"Failed to list events: {e}")
        return ActionResult(success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to list events: {e}")

def update_event(args: dict, credentials) -> ActionResult:
    event_id = args.get("event_id")
    try:
        service = build("calendar", "v3", credentials=credentials)
        patch_body = {}
        if args.get("title"):
            patch_body["summary"] = args["title"]
        if args.get("start"):
            patch_body["start"] = {"dateTime": args["start"]}
        if args.get("end"):
            patch_body["end"] = {"dateTime": args["end"]}
        if args.get("description"):
            patch_body["description"] = args["description"]
        event = service.events().patch(calendarId="primary", eventId=event_id, body=patch_body).execute()
        url = event.get("htmlLink", "")
        return ActionResult(success=True, data={"event_id": event["id"]},
                          display_message=f"Updated event", resource_url=url, error_message=None)
    except Exception as e:
        logger.exception(f"Failed to update event: {e}")
        return ActionResult(success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to update event: {e}")
