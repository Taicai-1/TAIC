"""Google Slides action implementations."""
from __future__ import annotations
import logging
import uuid
from googleapiclient.discovery import build
from plugins.base import ActionResult

logger = logging.getLogger(__name__)

def create_presentation(args: dict, credentials) -> ActionResult:
    title = args.get("title", "Untitled Presentation")
    slides_data = args.get("slides", [])
    try:
        service = build("slides", "v1", credentials=credentials)
        pres = service.presentations().create(body={"title": title}).execute()
        pres_id = pres["presentationId"]
        # Add slides
        for idx, slide_data in enumerate(slides_data):
            slide_id = str(uuid.uuid4()).replace("-", "")[:8]
            requests = [
                {"createSlide": {"objectId": slide_id, "insertionIndex": str(idx + 1),
                                "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"}}},
            ]
            service.presentations().batchUpdate(presentationId=pres_id, body={"requests": requests}).execute()
            # Insert text into title and body placeholders
            slide = service.presentations().get(presentationId=pres_id).execute()
            # Simple approach: insert text into the new slide's placeholders
            text_requests = []
            for page in slide.get("slides", []):
                if page["objectId"] == slide_id:
                    for element in page.get("pageElements", []):
                        shape = element.get("shape", {})
                        ph = shape.get("placeholder", {})
                        if ph.get("type") == "TITLE" and slide_data.get("title"):
                            text_requests.append({"insertText": {"objectId": element["objectId"], "text": slide_data["title"]}})
                        elif ph.get("type") == "BODY" and slide_data.get("body"):
                            text_requests.append({"insertText": {"objectId": element["objectId"], "text": slide_data["body"]}})
            if text_requests:
                service.presentations().batchUpdate(presentationId=pres_id, body={"requests": text_requests}).execute()
        url = f"https://docs.google.com/presentation/d/{pres_id}/edit"
        return ActionResult(success=True, data={"presentation_id": pres_id, "url": url},
                          display_message=f"Created presentation '{title}'", resource_url=url, error_message=None)
    except Exception as e:
        logger.exception(f"Failed to create presentation: {e}")
        return ActionResult(success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to create presentation: {e}")

def add_slide(args: dict, credentials) -> ActionResult:
    pres_id = args.get("presentation_id")
    title = args.get("title", "")
    body = args.get("body", "")
    try:
        service = build("slides", "v1", credentials=credentials)
        slide_id = str(uuid.uuid4()).replace("-", "")[:8]
        requests = [
            {"createSlide": {"objectId": slide_id, "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"}}},
        ]
        service.presentations().batchUpdate(presentationId=pres_id, body={"requests": requests}).execute()
        # Get the slide to find placeholder IDs
        pres = service.presentations().get(presentationId=pres_id).execute()
        text_requests = []
        for page in pres.get("slides", []):
            if page["objectId"] == slide_id:
                for element in page.get("pageElements", []):
                    shape = element.get("shape", {})
                    ph = shape.get("placeholder", {})
                    if ph.get("type") == "TITLE" and title:
                        text_requests.append({"insertText": {"objectId": element["objectId"], "text": title}})
                    elif ph.get("type") == "BODY" and body:
                        text_requests.append({"insertText": {"objectId": element["objectId"], "text": body}})
        if text_requests:
            service.presentations().batchUpdate(presentationId=pres_id, body={"requests": text_requests}).execute()
        url = f"https://docs.google.com/presentation/d/{pres_id}/edit"
        return ActionResult(success=True, data={"presentation_id": pres_id, "slide_id": slide_id},
                          display_message=f"Added slide to presentation", resource_url=url, error_message=None)
    except Exception as e:
        logger.exception(f"Failed to add slide: {e}")
        return ActionResult(success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to add slide: {e}")
