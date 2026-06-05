"""Google Sheets action implementations."""
from __future__ import annotations
import logging
from googleapiclient.discovery import build
from plugins.base import ActionResult

logger = logging.getLogger(__name__)

def create_sheet(args: dict, credentials) -> ActionResult:
    title = args.get("title", "Untitled Spreadsheet")
    sheets_data = args.get("sheets", [])
    try:
        service = build("sheets", "v4", credentials=credentials)
        body = {"properties": {"title": title}}
        if sheets_data:
            body["sheets"] = [{"properties": {"title": s.get("title") or s.get("name") or f"Sheet{i+1}"}} for i, s in enumerate(sheets_data)]
        ss = service.spreadsheets().create(body=body).execute()
        ss_id = ss["spreadsheetId"]
        # Write headers and rows if provided
        for i, sheet in enumerate(sheets_data):
            sheet_name = sheet.get("title") or sheet.get("name") or f"Sheet{i+1}"
            values = []
            if sheet.get("headers"):
                values.append(sheet["headers"])
            rows = sheet.get("rows") or sheet.get("data") or []
            if rows:
                values.extend(rows)
            if values:
                service.spreadsheets().values().update(
                    spreadsheetId=ss_id, range=f"{sheet_name}!A1",
                    valueInputOption="RAW", body={"values": values},
                ).execute()
        url = f"https://docs.google.com/spreadsheets/d/{ss_id}/edit"
        return ActionResult(success=True, data={"spreadsheet_id": ss_id, "url": url},
                          display_message=f"Created spreadsheet '{title}'", resource_url=url, error_message=None)
    except Exception as e:
        logger.exception(f"Failed to create spreadsheet: {e}")
        return ActionResult(success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to create spreadsheet: {e}")

def update_sheet(args: dict, credentials) -> ActionResult:
    ss_id = args.get("spreadsheet_id")
    range_ = args.get("range", "Sheet1!A1")
    values = args.get("values", [])
    try:
        service = build("sheets", "v4", credentials=credentials)
        service.spreadsheets().values().update(
            spreadsheetId=ss_id, range=range_, valueInputOption="RAW", body={"values": values},
        ).execute()
        url = f"https://docs.google.com/spreadsheets/d/{ss_id}/edit"
        return ActionResult(success=True, data={"spreadsheet_id": ss_id}, display_message=f"Updated spreadsheet",
                          resource_url=url, error_message=None)
    except Exception as e:
        logger.exception(f"Failed to update spreadsheet: {e}")
        return ActionResult(success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to update spreadsheet: {e}")

def read_sheet(args: dict, credentials) -> ActionResult:
    ss_id = args.get("spreadsheet_id")
    range_ = args.get("range", "Sheet1!A1:Z1000")
    try:
        service = build("sheets", "v4", credentials=credentials)
        result = service.spreadsheets().values().get(spreadsheetId=ss_id, range=range_).execute()
        values = result.get("values", [])
        return ActionResult(success=True, data={"values": values, "range": range_},
                          display_message=f"Read {len(values)} rows from spreadsheet", resource_url=None, error_message=None)
    except Exception as e:
        logger.exception(f"Failed to read spreadsheet: {e}")
        return ActionResult(success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to read spreadsheet: {e}")
