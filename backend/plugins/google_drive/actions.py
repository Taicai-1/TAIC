"""Google Drive action implementations."""
from __future__ import annotations
import logging
from googleapiclient.discovery import build
from plugins.base import ActionResult

logger = logging.getLogger(__name__)

def create_folder(args: dict, credentials) -> ActionResult:
    name = args.get("name", "Untitled Folder")
    parent_id = args.get("parent_id")
    try:
        service = build("drive", "v3", credentials=credentials)
        body = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent_id:
            body["parents"] = [parent_id]
        folder = service.files().create(body=body, fields="id,webViewLink").execute()
        url = folder.get("webViewLink", f"https://drive.google.com/drive/folders/{folder['id']}")
        return ActionResult(success=True, data={"folder_id": folder["id"], "url": url},
                          display_message=f"Created folder '{name}'", resource_url=url, error_message=None)
    except Exception as e:
        logger.exception(f"Failed to create folder: {e}")
        return ActionResult(success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to create folder: {e}")

def move_file(args: dict, credentials) -> ActionResult:
    file_id = args.get("file_id")
    folder_id = args.get("folder_id")
    try:
        service = build("drive", "v3", credentials=credentials)
        file = service.files().get(fileId=file_id, fields="parents").execute()
        previous_parents = ",".join(file.get("parents", []))
        service.files().update(fileId=file_id, addParents=folder_id, removeParents=previous_parents, fields="id,parents").execute()
        return ActionResult(success=True, data={"file_id": file_id, "folder_id": folder_id},
                          display_message=f"Moved file to folder", resource_url=None, error_message=None)
    except Exception as e:
        logger.exception(f"Failed to move file: {e}")
        return ActionResult(success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to move file: {e}")

def share_file(args: dict, credentials) -> ActionResult:
    file_id = args.get("file_id")
    email = args.get("email")
    role = args.get("role", "reader")
    try:
        service = build("drive", "v3", credentials=credentials)
        service.permissions().create(
            fileId=file_id, body={"type": "user", "role": role, "emailAddress": email},
            sendNotificationEmail=True,
        ).execute()
        return ActionResult(success=True, data={"file_id": file_id, "shared_with": email, "role": role},
                          display_message=f"Shared file with {email} as {role}", resource_url=None, error_message=None)
    except Exception as e:
        logger.exception(f"Failed to share file: {e}")
        return ActionResult(success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to share file: {e}")

def search_files(args: dict, credentials) -> ActionResult:
    query = args.get("query", "")
    max_results = args.get("max_results", 10)
    try:
        service = build("drive", "v3", credentials=credentials)
        results = service.files().list(q=query, pageSize=max_results, fields="files(id,name,mimeType,webViewLink,modifiedTime)").execute()
        files = results.get("files", [])
        summaries = [{"id": f["id"], "name": f["name"], "type": f.get("mimeType", ""), "url": f.get("webViewLink", ""),
                      "modified": f.get("modifiedTime", "")} for f in files]
        return ActionResult(success=True, data={"files": summaries, "total": len(summaries)},
                          display_message=f"Found {len(summaries)} files matching '{query}'", resource_url=None, error_message=None)
    except Exception as e:
        logger.exception(f"Failed to search files: {e}")
        return ActionResult(success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to search files: {e}")
