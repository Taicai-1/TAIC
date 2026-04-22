"""
Google Drive API Client
Lightweight client for fetching files from Google Drive folders.
Uses the Drive v3 REST API via the Google API client library.
Folder must be shared with the backend's Service Account.
"""

import io
import os
import re
import logging
import tempfile

logger = logging.getLogger(__name__)

# MIME types we can extract text from
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
GOOGLE_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
GOOGLE_SLIDES_MIME = "application/vnd.google-apps.presentation"
PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT_MIMES = {"text/plain", "text/csv", "text/markdown"}

SUPPORTED_MIMES = {
    GOOGLE_DOC_MIME,
    GOOGLE_SHEET_MIME,
    GOOGLE_SLIDES_MIME,
    PDF_MIME,
    DOCX_MIME,
} | TEXT_MIMES


def extract_drive_folder_id(url_or_id: str) -> str:
    """Extract a Google Drive folder ID from a URL or raw ID string."""
    url_or_id = url_or_id.strip()

    # URL pattern: https://drive.google.com/drive/folders/<ID>
    match = re.search(r"/folders/([a-zA-Z0-9_-]+)", url_or_id)
    if match:
        return match.group(1)

    # Raw ID: alphanumeric + hyphens + underscores
    if re.fullmatch(r"[a-zA-Z0-9_-]+", url_or_id) and len(url_or_id) > 10:
        return url_or_id

    raise ValueError(f"Cannot extract Drive folder ID from: {url_or_id}")


def get_drive_service(agent_id=None, db=None):
    """Build a Google Drive v3 service using the backend's service account."""
    from actions import _get_google_credentials
    from googleapiclient.discovery import build

    creds = _get_google_credentials(agent_id, db)
    if not creds:
        raise RuntimeError("Google service account credentials not available")
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def fetch_folder_name(folder_id: str, agent_id=None, db=None) -> str:
    """Fetch the name of a Drive folder (also validates access)."""
    service = get_drive_service(agent_id, db)
    result = service.files().get(fileId=folder_id, fields="name", supportsAllDrives=True).execute()
    return result.get("name", "Untitled folder")


def list_folder_files(folder_id: str, agent_id=None, db=None) -> list[dict]:
    """List all files (not sub-folders) in a Drive folder."""
    service = get_drive_service(agent_id, db)
    files = []
    page_token = None

    while True:
        resp = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken, files(id, name, mimeType, size)",
                pageSize=100,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        for f in resp.get("files", []):
            # Skip sub-folders
            if f.get("mimeType") == "application/vnd.google-apps.folder":
                continue
            files.append(
                {
                    "id": f["id"],
                    "name": f["name"],
                    "mimeType": f.get("mimeType", ""),
                    "size": int(f.get("size", 0)),
                }
            )
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return files


def download_file_content(service, file_id: str, mime_type: str) -> bytes:
    """Download file content from Drive. Exports Google Workspace files."""
    if mime_type == GOOGLE_DOC_MIME:
        resp = service.files().export(fileId=file_id, mimeType="text/plain").execute()
        return resp if isinstance(resp, bytes) else resp.encode("utf-8")

    if mime_type == GOOGLE_SHEET_MIME:
        resp = service.files().export(fileId=file_id, mimeType="text/csv").execute()
        return resp if isinstance(resp, bytes) else resp.encode("utf-8")

    if mime_type == GOOGLE_SLIDES_MIME:
        resp = service.files().export(fileId=file_id, mimeType="text/plain").execute()
        return resp if isinstance(resp, bytes) else resp.encode("utf-8")

    # Binary files (PDF, DOCX, TXT, etc.)
    request = service.files().get_media(fileId=file_id)
    from googleapiclient.http import MediaIoBaseDownload

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


def extract_text_from_drive_file(service, file_id: str, file_name: str, mime_type: str) -> str | None:
    """Download a Drive file and extract its text content. Returns None if unsupported."""
    if mime_type not in SUPPORTED_MIMES:
        logger.info(f"Skipping unsupported file: {file_name} ({mime_type})")
        return None

    try:
        raw = download_file_content(service, file_id, mime_type)
    except Exception as e:
        logger.warning(f"Failed to download {file_name}: {e}")
        return None

    # Google Workspace exports are already text
    if mime_type in (GOOGLE_DOC_MIME, GOOGLE_SHEET_MIME, GOOGLE_SLIDES_MIME):
        return raw.decode("utf-8", errors="replace")

    # Plain text / CSV
    if mime_type in TEXT_MIMES:
        return raw.decode("utf-8", errors="replace")

    # PDF
    if mime_type == PDF_MIME:
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(raw)
                tmp_path = tmp.name
            from file_loader import load_text_from_pdf

            text = load_text_from_pdf(tmp_path)
            os.unlink(tmp_path)
            return text
        except Exception as e:
            logger.warning(f"Failed to extract text from PDF {file_name}: {e}")
            return None

    # DOCX
    if mime_type == DOCX_MIME:
        try:
            import docx

            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
                tmp.write(raw)
                tmp_path = tmp.name
            doc = docx.Document(tmp_path)
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            os.unlink(tmp_path)
            return text
        except Exception as e:
            logger.warning(f"Failed to extract text from DOCX {file_name}: {e}")
            return None

    return None
