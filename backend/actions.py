import os
import json
import logging
from typing import Any, Callable, Dict, Optional

from google.cloud import secretmanager
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Simple action registry
ACTION_REGISTRY: Dict[str, Callable[..., Dict[str, Any]]] = {}


def register_action(name: str):
    """Decorator to register an action handler by name."""

    def deco(fn: Callable[..., Dict[str, Any]]):
        ACTION_REGISTRY[name] = fn
        return fn

    return deco


def _read_secret_from_secretmanager(secret_name: str, project_id: Optional[str] = None) -> Optional[str]:
    """Read a secret from Google Secret Manager. Returns the secret payload (string) or None."""
    try:
        client = secretmanager.SecretManagerServiceClient()
        project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT")
        if not project_id:
            logger.debug("No GOOGLE_CLOUD_PROJECT configured for Secret Manager access")
            return None
        name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        payload = response.payload.data.decode("utf-8")
        return payload
    except Exception as e:
        logger.debug(f"Could not read secret {secret_name} from Secret Manager: {e}")
        return None


def _get_google_credentials(agent_id: Optional[int], db: Optional[Session] = None) -> Optional[Any]:
    """Attempt to load Google service account credentials for a given agent.

    Heuristics used (in order):
    - Secret Manager secret named 'agent-{id}-google-sa' (project from env)
    - Environment variable named AGENT_{id}_GOOGLE_SA (full JSON string)
    - Agent table field named 'google_service_account' or 'service_account_json' (if present)
    - GOOGLE_APPLICATION_CREDENTIALS file path or GOOGLE_SERVICE_ACCOUNT env var

    Returns google.oauth2.service_account.Credentials or None.
    """
    try:
        creds_info = None

        # 1) Shared Secret Manager secret (global override) — prefer this for all agents.
        #    Set DEFAULT_GOOGLE_SECRET_NAME or SHARED_GOOGLE_SECRET_NAME in the environment to configure it.
        shared_secret = os.getenv("DEFAULT_GOOGLE_SECRET_NAME") or os.getenv("SHARED_GOOGLE_SECRET_NAME")
        if shared_secret:
            payload = _read_secret_from_secretmanager(shared_secret)
            if payload:
                try:
                    creds_info = json.loads(payload)
                    logger.info(
                        f"Loaded service account JSON from shared Secret Manager '{shared_secret}' for agent {agent_id}"
                    )
                except Exception:
                    creds_info = payload
                    logger.info(f"Loaded shared secret '{shared_secret}' for agent {agent_id} (non-JSON payload)")

        # 2) If no shared secret found, fallback to per-agent secret names for backwards compatibility
        if creds_info is None and agent_id is not None:
            candidate_names = [
                f"agent-{agent_id}-google-sa",
                f"agent-{agent_id}-sa-key",
                f"agent-{agent_id}-sa",
                f"agent-{agent_id}-key",
            ]
            for secret_name in candidate_names:
                payload = _read_secret_from_secretmanager(secret_name)
                if payload:
                    try:
                        creds_info = json.loads(payload)
                        logger.info(
                            f"Loaded service account JSON from Secret Manager '{secret_name}' for agent {agent_id}"
                        )
                    except Exception:
                        # If not JSON, assume raw key string
                        creds_info = payload
                        logger.info(f"Loaded secret '{secret_name}' for agent {agent_id} (non-JSON payload)")
                    break

        # 2) Environment variable per-agent
        if creds_info is None and agent_id is not None:
            env_name = f"AGENT_{agent_id}_GOOGLE_SA"
            if os.getenv(env_name):
                try:
                    creds_info = json.loads(os.getenv(env_name))
                    logger.info(f"Loaded service account JSON from env {env_name} for agent {agent_id}")
                except Exception:
                    creds_info = os.getenv(env_name)

        # 3) Check DB Agent fields if db provided
        if creds_info is None and db is not None and agent_id is not None:
            try:
                from database import Agent

                agent = db.query(Agent).filter(Agent.id == agent_id).first()
                if agent:
                    # Try common field names (under-specification tolerant).
                    # Also support `google_secret_name` which is expected to contain the Secret Manager secret name
                    # that holds the service account JSON. If present, we will attempt to read that secret.
                    for field in (
                        "google_secret_name",
                        "google_service_account",
                        "service_account_json",
                        "google_sa_json",
                    ):
                        if hasattr(agent, field) and getattr(agent, field):
                            raw = getattr(agent, field)
                            try:
                                # If the agent row stores a secret name reference, fetch it from Secret Manager
                                if field == "google_secret_name" and isinstance(raw, str):
                                    payload = _read_secret_from_secretmanager(raw)
                                    if payload:
                                        try:
                                            creds_info = json.loads(payload)
                                            logger.info(
                                                f"Loaded service account JSON from Secret Manager '{raw}' referenced in Agent.google_secret_name for agent {agent_id}"
                                            )
                                        except Exception:
                                            creds_info = payload
                                            logger.info(
                                                f"Loaded secret '{raw}' referenced in Agent.google_secret_name for agent {agent_id} (non-JSON payload)"
                                            )
                                        break
                                    else:
                                        # If the secret name didn't resolve, continue to next candidate
                                        continue

                                # Otherwise, try to interpret the DB field as JSON or raw string/json dict
                                if isinstance(raw, dict):
                                    creds_info = raw
                                    logger.info(
                                        f"Loaded service account JSON dict from DB Agent.{field} for agent {agent_id}"
                                    )
                                elif isinstance(raw, str):
                                    try:
                                        creds_info = json.loads(raw)
                                        logger.info(
                                            f"Loaded service account JSON from DB Agent.{field} for agent {agent_id}"
                                        )
                                    except Exception:
                                        # Non-JSON string (could be raw key or another secret identifier)
                                        creds_info = raw
                                        logger.info(
                                            f"Loaded service account raw value from DB Agent.{field} for agent {agent_id}"
                                        )
                                else:
                                    # Fallback: coerce to string
                                    creds_info = str(raw)
                                    logger.info(
                                        f"Loaded service account value from DB Agent.{field} for agent {agent_id}"
                                    )
                                break
                            except Exception as e:
                                logger.debug(f"Error while loading credentials from Agent.{field}: {e}")
            except Exception as e:
                logger.debug(f"Could not load agent row from DB to find credentials: {e}")

        # 4) Global env or file
        if creds_info is None:
            if os.getenv("GOOGLE_SERVICE_ACCOUNT"):
                try:
                    creds_info = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT"))
                    logger.info("Loaded service account JSON from GOOGLE_SERVICE_ACCOUNT env var")
                except Exception:
                    creds_info = os.getenv("GOOGLE_SERVICE_ACCOUNT")
            elif os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
                path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        creds_info = json.load(f)
                    logger.info(f"Loaded service account JSON from file {path}")
                except Exception as e:
                    logger.debug(f"Failed to read GOOGLE_APPLICATION_CREDENTIALS file {path}: {e}")

        # Build Credentials object if we have JSON dict
        if creds_info:
            try:
                # lazy import to avoid hard dependency if not used
                from google.oauth2 import service_account

                if isinstance(creds_info, dict):
                    creds = service_account.Credentials.from_service_account_info(
                        creds_info,
                        scopes=[
                            "https://www.googleapis.com/auth/documents",
                            "https://www.googleapis.com/auth/drive",
                            "https://www.googleapis.com/auth/spreadsheets",
                        ],
                    )
                    # Log the client_email if available (non-secret)
                    client_email = creds_info.get("client_email") if isinstance(creds_info, dict) else None
                    logger.info(f"Using service account: {client_email}")
                    return creds
                else:
                    logger.debug("Service account found but not JSON dict; cannot build Credentials from it")
            except Exception as e:
                logger.debug(f"Failed to create Google credentials object: {e}")

        # 5) Fallback: Application Default Credentials (Cloud Run SA via Workload Identity)
        try:
            import google.auth

            SCOPES = [
                "https://www.googleapis.com/auth/documents",
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/spreadsheets",
            ]
            creds, project = google.auth.default(scopes=SCOPES)
            logger.info(f"Using Application Default Credentials (project={project})")
            return creds
        except Exception as e:
            logger.debug(f"ADC fallback failed: {e}")

    except Exception as e:
        logger.debug(f"_get_google_credentials unexpected error: {e}")
    return None


def _safe_parse_args(arguments: Any) -> Dict[str, Any]:
    """Normalize 'arguments' which may be a JSON string or a dict."""
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            return json.loads(arguments)
        except Exception:
            # Not JSON — return raw string in a conventional key
            return {"_raw": arguments}
    return {"_raw": str(arguments)}


@register_action("echo")
def action_echo(
    params: Dict[str, Any], db: Optional[Session] = None, agent_id: Optional[int] = None, user_id: Optional[int] = None
) -> Dict[str, Any]:
    """Return back the provided text."""
    text = params.get("text") or params.get("content") or params.get("message") or ""
    return {"status": "ok", "result": {"text": str(text)}}


@register_action("write_local_file")
def action_write_local_file(
    params: Dict[str, Any], db: Optional[Session] = None, agent_id: Optional[int] = None, user_id: Optional[int] = None
) -> Dict[str, Any]:
    """Write a file on the local filesystem (useful for debug). Returns path."""
    filename = params.get("filename") or params.get("name") or "output.txt"
    content = params.get("content") or params.get("text") or ""
    safe_dir = os.getenv("LOCAL_ACTIONS_DIR", "/tmp")
    try:
        os.makedirs(safe_dir, exist_ok=True)
        path = os.path.join(safe_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(content))
        return {"status": "ok", "result": {"path": path}}
    except Exception as e:
        logger.error(f"write_local_file failed: {e}")
        return {"status": "error", "error": str(e)}


@register_action("create_google_doc")
def action_create_google_doc(
    params: Dict[str, Any], db: Optional[Session] = None, agent_id: Optional[int] = None, user_id: Optional[int] = None
) -> Dict[str, Any]:
    """Create a Google Doc using service account credentials.

    Expected params: title (str), content (str), folder_id (optional, drive folder to place the doc)
    """
    title = params.get("title") or params.get("name") or "New Document"
    content = params.get("content") or params.get("text") or ""
    folder_id = params.get("folder_id") or params.get("drive_folder_id")

    # If no folder_id provided, allow a hardcoded default for agent 52 (user-provided)
    # This is a convenience fallback — consider using Secret Manager or env var for production.
    if not folder_id:
        folder_id = "0APAdOvpsKAuQUk9PVA"
        logger.info(f"No folder_id provided — using default Shared Drive folder for agent {agent_id}: {folder_id}")

    # If no content provided, ask the LLM (deterministic) to generate suitable document content from the prompt/title.
    if not content:
        raw_prompt = params.get("prompt") or params.get("prompt_text") or params.get("_raw") or ""
        instruction = (
            f"Write the full plain-text content for a Google Document titled '{title}'.\n"
            "Do not include metadata or explanations — output only the document body text.\n"
        )
        if raw_prompt:
            instruction += "Original user prompt: \n" + raw_prompt

        try:
            from openai_client import get_chat_response_deterministic

            # If this action is executed for an actionnable agent, enforce Gemini-only
            gemini_only_flag = False
            try:
                if agent_id and db is not None:
                    from database import Agent as DbAgent

                    a = db.query(DbAgent).filter(DbAgent.id == agent_id).first()
                    gemini_only_flag = bool(a and getattr(a, "type", "") == "actionnable")
            except Exception:
                gemini_only_flag = False

            resp = get_chat_response_deterministic(
                [
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that outputs only the requested document text, no extra commentary.",
                    },
                    {"role": "user", "content": instruction},
                ],
                None,
                temperature=0.0,
                max_tokens=16000,
                gemini_only=gemini_only_flag,
            )
            # Clean common wrappers (markdown code fences etc.)
            content = resp.strip()
            if content.startswith("```"):
                import re

                m = re.search(r"```(?:\w+)?\n([\s\S]*?)```", content)
                if m:
                    content = m.group(1).strip()
        except Exception as e_gen:
            logger.debug(f"Could not generate doc content via LLM: {e_gen}")
            return {
                "status": "error",
                "error": "No content provided for create_google_doc and LLM generation failed",
                "hint": "Ensure the model is reachable or provide content in params.",
            }

    creds = _get_google_credentials(agent_id, db)
    if not creds:
        return {
            "status": "error",
            "error": "Google credentials not found for agent",
            "hint": "Store a service account JSON in Secret Manager named 'agent-{agent_id}-google-sa' or set GOOGLE_SERVICE_ACCOUNT env var.",
        }

    try:
        # Lazy import to avoid hard dependency when actions are unused
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError

        docs_service = build("docs", "v1", credentials=creds)
        drive_service = build("drive", "v3", credentials=creds)
        # Log which identity we're using and the target folder for debugging
        try:
            sa_email = getattr(creds, "service_account_email", None) or getattr(creds, "_service_account_email", None)
        except Exception:
            sa_email = None
        logger.info(f"create_google_doc using credentials for: {sa_email}, target folder_id={folder_id}")

        # Prefer creating directly in the target folder via Drive API when a folder_id is provided.
        # This ensures the file is owned by the Shared Drive (supportsAllDrives=True) and avoids
        # the service-account "limit=0" issue where the SA cannot own My Drive files.
        doc_id = None
        created_via = None
        if folder_id:
            try:
                drive_body = {"name": title, "mimeType": "application/vnd.google-apps.document", "parents": [folder_id]}
                created = drive_service.files().create(body=drive_body, supportsAllDrives=True, fields="id").execute()
                doc_id = created.get("id")
                created_via = "drive"
                logger.info(f"Created document via Drive API in folder {folder_id}, id={doc_id}")
            except Exception as e_drive_create:
                # Log detail and fall back to trying the Docs API create (without parent)
                try:
                    content = getattr(e_drive_create, "content", None)
                    content_str = content.decode("utf-8") if isinstance(content, (bytes, bytearray)) else str(content)
                    logger.error(f"Drive API create failed when targeting folder {folder_id}: {content_str}")
                except Exception:
                    logger.exception("Drive API create failed when targeting folder; attempting Docs API create")
                # continue to try Docs API below

        if not doc_id:
            # Create the document via Docs API; if that fails due to permission, fall back to Drive API
            try:
                doc_body = {"title": title}
                doc = docs_service.documents().create(body=doc_body).execute()
                doc_id = doc.get("documentId")
                created_via = "docs"
            except Exception as e_docs:
                # If Docs API call fails with a permission error, try to create via Drive API as a fallback
                try:
                    from googleapiclient.errors import HttpError as _HttpError

                    is_http403 = False
                    try:
                        is_http403 = (
                            isinstance(e_docs, _HttpError)
                            and getattr(e_docs, "resp", None)
                            and getattr(e_docs, "resp").status == 403
                        )
                    except Exception:
                        is_http403 = False
                except Exception:
                    is_http403 = False

                # If we have an HttpError, try to capture its content for debugging
                try:
                    content = getattr(e_docs, "content", None)
                    content_str = content.decode("utf-8") if isinstance(content, (bytes, bytearray)) else str(content)
                    logger.error(f"Docs API create HttpError content: {content_str}")
                except Exception:
                    pass

                if is_http403:
                    logger.info(f"Docs API create failed with 403, trying Drive API fallback for title={title}")
                    try:
                        drive_body = {"name": title, "mimeType": "application/vnd.google-apps.document"}
                        created = drive_service.files().create(body=drive_body, fields="id").execute()
                        doc_id = created.get("id")
                        created_via = "drive_fallback"
                    except Exception as e_drive_fallback:
                        # If fallback also fails, re-raise the original error to be handled below
                        raise e_docs
                else:
                    # Non-permission error from Docs API — re-raise to be handled below
                    raise

        # Try to insert content via Docs API if we have a document id.
        content_inserted = False
        if content and doc_id:
            try:
                requests = [{"insertText": {"location": {"index": 1}, "text": content}}]
                docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
                content_inserted = True
                logger.info(f"Inserted initial content into document {doc_id}")
            except Exception as e_ins:
                # Could fail due to Docs API permission when doc is created via Drive under some policies
                logger.warning(f"Could not insert content into document {doc_id} via Docs API: {e_ins}")

        # If a folder is provided, move the file into the folder
        if folder_id:
            try:
                # Retrieve the current parents to remove
                file = drive_service.files().get(fileId=doc_id, fields="parents").execute()
                previous_parents = ",".join(file.get("parents", []))
                drive_service.files().update(
                    fileId=doc_id, addParents=folder_id, removeParents=previous_parents, fields="id, parents"
                ).execute()
            except Exception as e:
                logger.debug(f"Failed to move doc to folder {folder_id}: {e}")

        # Build a shareable link
        web_view_link = f"https://docs.google.com/document/d/{doc_id}/edit"
        result = {"document_id": doc_id, "url": web_view_link}
        if created_via in ("drive", "drive_fallback") and not content_inserted:
            # Inform caller that initial content may not have been inserted via Docs API
            return {
                "status": "ok",
                "result": result,
                "note": "Document created via Drive API; initial content could not be inserted via Docs API (permission may be missing).",
            }
        return {"status": "ok", "result": result}

    except ImportError as e:
        logger.error(f"Google API client libraries not installed: {e}")
        return {
            "status": "error",
            "error": "googleapiclient not installed",
            "hint": "pip install google-api-python-client google-auth",
        }
    except Exception as e:
        # Help with common permission errors and quota errors
        msg = str(e)
        hint = None
        try:
            # Re-import HttpError to inspect content if available
            from googleapiclient.errors import HttpError as _HttpError

            if isinstance(e, _HttpError):
                # e.content may be bytes containing JSON with details
                content = getattr(e, "content", None)
                try:
                    content_str = content.decode("utf-8") if isinstance(content, (bytes, bytearray)) else str(content)
                except Exception:
                    content_str = str(content)

                # Detect storage quota exceeded error and return a clear hint
                if content_str and (
                    "storageQuotaExceeded" in content_str
                    or "Drive storage quota" in content_str
                    or "The user's Drive storage quota has been exceeded" in content_str
                ):
                    hint = (
                        "Drive storage quota exceeded for the folder owner. "
                        "Ask the folder owner to free space or move the folder to a Shared Drive, or give the service account access to a Shared Drive."
                    )
                    logger.error(f"create_google_doc quota error: {msg}")
                    return {"status": "error", "error": msg, "hint": hint}

        except Exception:
            # Fall through to generic handling
            pass

        if hasattr(e, "resp") and getattr(e, "resp").status == 403:
            hint = "403 from Google Docs API. Ensure the Docs & Drive APIs are enabled in the project that owns the service account and that the target Drive folder (if used) is shared with the service account email as Editor."
        logger.error(f"create_google_doc error: {e}")
        return {"status": "error", "error": msg, "hint": hint}


@register_action("create_google_sheet")
def action_create_google_sheet(
    params: Dict[str, Any], db: Optional[Session] = None, agent_id: Optional[int] = None, user_id: Optional[int] = None
) -> Dict[str, Any]:
    """Create a Google Sheet and optionally populate rows.

    Expected params: title, rows (list of lists of strings), folder_id
    """
    title = params.get("title") or params.get("name") or "New Sheet"
    rows = params.get("rows") or []
    # Optional: allow explicit headers structure
    sheets_spec = params.get("sheets")
    folder_id = params.get("folder_id")

    # Default folder fallback for agent 52 if not provided
    if not folder_id:
        folder_id = "0APAdOvpsKAuQUk9PVA"
        logger.info(
            f"No folder_id provided for sheet — using default Shared Drive folder for agent {agent_id}: {folder_id}"
        )

    creds = _get_google_credentials(agent_id, db)
    if not creds:
        return {
            "status": "error",
            "error": "Google credentials not found for agent",
            "hint": "Store a service account JSON in Secret Manager named 'agent-{agent_id}-google-sa' or set GOOGLE_SERVICE_ACCOUNT env var.",
        }

    # If the caller did not provide a sheets specification (headers/rows/etc), ask the LLM to generate a JSON spec from the original prompt
    if not sheets_spec:
        # Try to extract a raw prompt from params (safe parsed payload sometimes stores raw text under _raw)
        raw_prompt = params.get("prompt") or params.get("prompt_text") or params.get("_raw") or ""
        # Build a short instruction for the model using the title and any available raw prompt
        instruction = (
            f"Generate a JSON specification for a Google Spreadsheet titled '{title}'.\n"
            'The JSON must have the shape: {"sheets": [{"title": string, "headers": [string,...], "rows": [[...],...], "formulas": [{"range": string, "formula": string}] , "conditional_formats": [{...}] }], \'title\': string }\n'
            "Only output the JSON object, no prose. If no sample rows are available, return rows: [] .\n"
        )
        if raw_prompt:
            instruction += "Original user prompt: \n" + raw_prompt

        try:
            # Lazy import to avoid hard dependency if OpenAI not configured
            from openai_client import get_chat_response_deterministic

            # Determine gemini-only enforcement for this agent
            gemini_only_flag = False
            try:
                if agent_id and db is not None:
                    from database import Agent as DbAgent

                    a = db.query(DbAgent).filter(DbAgent.id == agent_id).first()
                    gemini_only_flag = bool(a and getattr(a, "type", "") == "actionnable")
            except Exception:
                gemini_only_flag = False

            # Call the model to get JSON spec (deterministic, parseable JSON)
            resp = get_chat_response_deterministic(
                [
                    {"role": "system", "content": "You are a helpful assistant that returns ONLY JSON."},
                    {"role": "user", "content": instruction},
                ],
                None,
                temperature=0.0,
                max_tokens=16000,
                gemini_only=gemini_only_flag,
            )
            try:
                spec = json.loads(resp)
                sheets_spec = spec.get("sheets") or spec
            except Exception:
                # Try to recover if model wrapped JSON in markdown or text
                import re

                m = re.search(r"\{[\s\S]*\}", resp)
                if m:
                    try:
                        spec = json.loads(m.group(0))
                        sheets_spec = spec.get("sheets") or spec
                    except Exception:
                        sheets_spec = None
                else:
                    sheets_spec = None
        except Exception as e_js:
            logger.debug(f"Could not generate sheets spec from model: {e_js}")

    # If we now have a sheets_spec, convert it to a headers/rows structure used below
    # Expected sheets_spec: list of {title, headers, rows, formulas, conditional_formats}
    # We'll use the first sheet's headers/rows for Employés population if rows param absent
    if sheets_spec and isinstance(sheets_spec, list) and not rows:
        try:
            # Find a sheet named Employés or the first sheet
            target = None
            for s in sheets_spec:
                t = s.get("title", "").lower()
                if "employ" in t or "employés" in t or "employees" in t:
                    target = s
                    break
            if not target and sheets_spec:
                target = sheets_spec[0]
            if target:
                hdrs = target.get("headers") or []
                sample_rows = target.get("rows") or []
                # Only accept if headers look like the expected 4 columns; otherwise ignore
                if hdrs:
                    # convert rows of dicts to lists if necessary
                    if sample_rows and isinstance(sample_rows[0], dict):
                        # map dict rows to header order
                        def dict_row_to_list(r):
                            return [r.get(h, "") for h in hdrs]

                        rows = [dict_row_to_list(r) for r in sample_rows]
                    else:
                        rows = sample_rows
        except Exception as e_conv:
            logger.debug(f"Could not convert sheets_spec to rows: {e_conv}")
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError

        # disable discovery cache warning by passing cache_discovery=False
        sheets_service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)

        spreadsheet_body = {"properties": {"title": title}}
        try:
            spreadsheet = sheets_service.spreadsheets().create(body=spreadsheet_body, fields="spreadsheetId").execute()
            sheet_id = spreadsheet.get("spreadsheetId")
        except HttpError as he:
            # Capture and log the full HttpError content for debugging permission issues
            content = getattr(he, "content", None)
            try:
                content_str = content.decode("utf-8") if isinstance(content, (bytes, bytearray)) else str(content)
            except Exception:
                content_str = str(content)
            status_code = None
            try:
                status_code = getattr(he, "resp", None) and getattr(he.resp, "status", None)
            except Exception:
                status_code = None
            logger.error(f"Sheets API create HttpError status={status_code} content={content_str}")

            # Attempt fallback: create the spreadsheet via Drive API (useful for Shared Drives / SA restrictions)
            try:
                drive_body = {"name": title, "mimeType": "application/vnd.google-apps.spreadsheet"}
                if folder_id:
                    drive_body["parents"] = [folder_id]
                created = drive_service.files().create(body=drive_body, supportsAllDrives=True, fields="id").execute()
                sheet_id = created.get("id")
                logger.info(f"Fallback: created spreadsheet via Drive API id={sheet_id}")
            except Exception as e_drive_fb:
                # If fallback fails, log and return structured error
                fb_content = getattr(e_drive_fb, "content", None)
                try:
                    fb_content_str = (
                        fb_content.decode("utf-8") if isinstance(fb_content, (bytes, bytearray)) else str(fb_content)
                    )
                except Exception:
                    fb_content_str = str(fb_content)
                logger.error(f"Drive fallback create failed content={fb_content_str}")
                return {
                    "status": "error",
                    "error": "Sheets API create failed and Drive fallback also failed",
                    "hint": content_str + " | fallback: " + fb_content_str,
                }

        # Now ensure the workbook has the three sheets and the requested headers, formulas and conditional formatting
        try:
            # Fetch metadata to get sheetIds
            meta = sheets_service.spreadsheets().get(spreadsheetId=sheet_id).execute()
            sheets_map = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}
            # If default sheet present, rename it to 'Employés', otherwise add sheets explicitly
            requests = []
            if meta.get("sheets"):
                default_sheet_id = meta["sheets"][0]["properties"]["sheetId"]
                requests.append(
                    {
                        "updateSheetProperties": {
                            "properties": {"sheetId": default_sheet_id, "title": "Employés"},
                            "fields": "title",
                        }
                    }
                )
            # Add 'Congés' and 'Résumé' if they don't exist
            existing_titles = [s["properties"]["title"] for s in meta.get("sheets", [])]
            if "Congés" not in existing_titles:
                requests.append({"addSheet": {"properties": {"title": "Congés"}}})
            if "Résumé" not in existing_titles:
                requests.append({"addSheet": {"properties": {"title": "Résumé"}}})

            if requests:
                sheets_service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": requests}).execute()

            # Prepare header rows for Employés and Congés
            header_requests = {
                "valueInputOption": "USER_ENTERED",
                "data": [
                    {"range": "Employés!A1:D1", "values": [["Nom", "Département", "Poste", "Salaire mensuel"]]},
                    {"range": "Congés!A1:D1", "values": [["Nom", "Date de début", "Date de fin", "Nombre de jours"]]},
                    {"range": "Résumé!A1:C1", "values": [["Département", "Nb employés", "Salaire moyen"]]},
                ],
            }
            sheets_service.spreadsheets().values().batchUpdate(spreadsheetId=sheet_id, body=header_requests).execute()

            # Insert formulas for Résumé: UNIQUE list of departments and COUNT/AVERAGE formulas
            # Put UNIQUE formula in A2, Count and Average in B2/C2 (will auto-expand when UNIQUE returns values)
            formula_values = {
                "valueInputOption": "USER_ENTERED",
                "data": [
                    {"range": "Résumé!A2", "values": [["=UNIQUE(FILTER(Employés!B2:B, LEN(Employés!B2:B)))"]]},
                    {"range": "Résumé!B2", "values": [['=IF(A2="","",COUNTIF(Employés!B:B,A2))']]},
                    {"range": "Résumé!C2", "values": [['=IF(A2="","",AVERAGEIF(Employés!B:B,A2,Employés!D:D))']]},
                ],
            }
            sheets_service.spreadsheets().values().batchUpdate(spreadsheetId=sheet_id, body=formula_values).execute()

            # Apply conditional formatting to Employés!D (Salaire mensuel): green >3000, red <2000
            # Need to re-fetch sheetId for Employés
            meta = sheets_service.spreadsheets().get(spreadsheetId=sheet_id).execute()
            sheet_id_map = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}
            employes_sheet_id = sheet_id_map.get("Employés")
            if employes_sheet_id is not None:
                cond_requests = [
                    {
                        "addConditionalFormatRule": {
                            "rule": {
                                "ranges": [
                                    {
                                        "sheetId": employes_sheet_id,
                                        "startRowIndex": 1,
                                        "startColumnIndex": 3,
                                        "endColumnIndex": 4,
                                    }
                                ],
                                "booleanRule": {
                                    "condition": {"type": "NUMBER_GREATER", "values": [{"userEnteredValue": "3000"}]},
                                    "format": {"backgroundColor": {"red": 0.8, "green": 1.0, "blue": 0.8}},
                                },
                            },
                            "index": 0,
                        }
                    },
                    {
                        "addConditionalFormatRule": {
                            "rule": {
                                "ranges": [
                                    {
                                        "sheetId": employes_sheet_id,
                                        "startRowIndex": 1,
                                        "startColumnIndex": 3,
                                        "endColumnIndex": 4,
                                    }
                                ],
                                "booleanRule": {
                                    "condition": {"type": "NUMBER_LESS", "values": [{"userEnteredValue": "2000"}]},
                                    "format": {"backgroundColor": {"red": 1.0, "green": 0.8, "blue": 0.8}},
                                },
                            },
                            "index": 0,
                        }
                    },
                ]
                sheets_service.spreadsheets().batchUpdate(
                    spreadsheetId=sheet_id, body={"requests": cond_requests}
                ).execute()

            # If rows param provided, write them starting at A2 of Employés
            if rows:
                body = {"values": rows}
                sheets_service.spreadsheets().values().update(
                    spreadsheetId=sheet_id, range="Employés!A2", valueInputOption="RAW", body=body
                ).execute()

        except Exception as e_setup:
            logger.warning(f"Failed to fully populate spreadsheet {sheet_id}: {e_setup}")

        # Move to folder if requested
        if folder_id:
            try:
                file = drive_service.files().get(fileId=sheet_id, fields="parents").execute()
                previous_parents = ",".join(file.get("parents", []))
                drive_service.files().update(
                    fileId=sheet_id,
                    addParents=folder_id,
                    removeParents=previous_parents,
                    fields="id, parents",
                    supportsAllDrives=True,
                ).execute()
            except Exception as e:
                logger.debug(f"Failed to move sheet to folder {folder_id}: {e}")

        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        return {"status": "ok", "result": {"spreadsheet_id": sheet_id, "url": url}}

    except ImportError as e:
        logger.error(f"Google API client libraries not installed: {e}")
        return {
            "status": "error",
            "error": "googleapiclient not installed",
            "hint": "pip install google-api-python-client google-auth",
        }
    except Exception as e:
        msg = str(e)
        hint = None
        try:
            from googleapiclient.errors import HttpError as _HttpError

            if isinstance(e, _HttpError):
                content = getattr(e, "content", None)
                try:
                    content_str = content.decode("utf-8") if isinstance(content, (bytes, bytearray)) else str(content)
                except Exception:
                    content_str = str(content)

                if content_str and (
                    "storageQuotaExceeded" in content_str
                    or "Drive storage quota" in content_str
                    or "The user's Drive storage quota has been exceeded" in content_str
                ):
                    hint = (
                        "Drive storage quota exceeded for the folder owner. "
                        "Ask the folder owner to free space or move the folder to a Shared Drive, or give the service account access to a Shared Drive."
                    )
                    logger.error(f"create_google_sheet quota error: {msg}")
                    return {"status": "error", "error": msg, "hint": hint}
        except Exception:
            pass

        try:
            if hasattr(e, "resp") and getattr(e, "resp").status == 403:
                hint = "403 from Google Sheets API. Ensure the Sheets & Drive APIs are enabled in the project that owns the service account and that the target Drive folder (if used) is shared with the service account email as Editor."
        except Exception:
            pass
        logger.error(f"create_google_sheet error: {e}")
        return {"status": "error", "error": msg, "hint": hint}


def execute_action_by_name(
    name: str,
    arguments: Any,
    db: Optional[Session] = None,
    agent_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Find and execute a registered action by name. Arguments may be a dict or JSON string."""
    fn = ACTION_REGISTRY.get(name)
    args = _safe_parse_args(arguments)
    if not fn:
        return {"status": "error", "error": f"Unknown action '{name}'"}

    try:
        # Execute the action handler
        result = fn(args, db=db, agent_id=agent_id, user_id=user_id)
        return result
    except Exception as e:
        logger.exception(f"Action {name} raised exception: {e}")
        return {"status": "error", "error": str(e)}


def parse_and_execute_actions(
    payload: Any,
    db: Optional[Session] = None,
    agent_id: Optional[int] = None,
    user_id: Optional[int] = None,
    company_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Parse a function-call-like payload and execute the corresponding action.

    Payload formats supported:
    - {'name': 'action_name', 'arguments': {...}}  (OpenAI function-call style)
    - JSON string representing the above
    - A dict with 'action' and 'params'
    """
    # Normalize payload
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return {"status": "error", "error": "Could not parse payload string as JSON"}

    if not isinstance(payload, dict):
        return {"status": "error", "error": "Unsupported payload type"}

    # Support OpenAI function call shape
    name = payload.get("name") or payload.get("action")
    arguments = payload.get("arguments") or payload.get("params") or payload.get("parameters")

    if not name:
        return {"status": "error", "error": "No action name provided in payload"}

    # Persist an audit row if DB session provided
    audit = None
    try:
        if db is not None:
            try:
                from database import AgentAction

                audit = AgentAction(
                    user_id=int(user_id) if user_id is not None else None,
                    agent_id=int(agent_id) if agent_id is not None else None,
                    company_id=company_id,
                    action_type=name,
                    params=json.dumps(arguments) if arguments is not None else None,
                    status="pending",
                )
                db.add(audit)
                db.commit()
                db.refresh(audit)
            except Exception as e:
                # Surface DB write failures loudly so they are visible in logs during debugging
                logger.exception(f"Could not write initial AgentAction audit row: {e}")

    except Exception:
        pass

    # Execute the action
    result = execute_action_by_name(name, arguments, db=db, agent_id=agent_id, user_id=user_id)

    # Update audit row with result/status
    if audit is not None:
        try:
            audit.result = json.dumps(result)
            audit.status = "ok" if result.get("status") == "ok" else "error"
            db.add(audit)
            db.commit()
            db.refresh(audit)
        except Exception as e:
            logger.exception(f"Could not update AgentAction audit row: {e}")

    return result


# Expose registry list for introspection
def list_actions() -> Dict[str, str]:
    return {k: v.__doc__ or "" for k, v in ACTION_REGISTRY.items()}
